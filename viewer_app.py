#!/usr/bin/env python3
"""
OpenRadiomics - 3D Voxel MRI Viewer
Flask Backend serving MRI volume data to Three.js frontend.

Supports both local filesystem and S3 storage for DICOM files.
HIPAA-compliant authentication via AWS Cognito.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from urllib.parse import urljoin

import numpy as np
import pydicom
from flask import Flask, jsonify, render_template, request, redirect, url_for, make_response

app = Flask(__name__)

# Secret key for Flask sessions (set via environment variable in production)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Import auth module
from auth import (
    get_current_user,
    is_authenticated,
    is_public_route,
    requires_auth,
    requires_role,
    log_audit,
    get_cognito_login_url,
    get_cognito_logout_url,
    exchange_code_for_tokens,
    refresh_tokens,
    ensure_user_in_db,
    validate_registration_data,
    create_cognito_user,
    normalize_phone,
    COGNITO_CLIENT_ID,
    COGNITO_DOMAIN,
)

# Configuration
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "brain_inventory.db"

# S3 configuration (set via environment variables)
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
USE_S3 = bool(S3_BUCKET_NAME)

# Initialize S3 client if configured
s3_client = None
if USE_S3:
    import boto3
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    print(f"S3 storage enabled: {S3_BUCKET_NAME}")
else:
    print(f"Local storage mode. Database: {DB_PATH}")

# Volume cache for orthogonal slicing
volume_cache = {}

# Local cache directory for S3 files
CACHE_DIR = Path(tempfile.gettempdir()) / "dicom_cache"
CACHE_DIR.mkdir(exist_ok=True)

# Auth configuration
# Always enable auth - redirects to login page even if Cognito isn't configured yet
AUTH_ENABLED = True


def get_callback_url():
    """Get the OAuth callback URL based on the request."""
    # Use X-Forwarded headers if behind a proxy/load balancer
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}/auth/callback"


def get_base_url():
    """Get the base URL for redirects."""
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}"


# ============================================================================
# AUTHENTICATION MIDDLEWARE
# ============================================================================

@app.before_request
def check_authentication():
    """Check authentication before each request."""
    # Skip auth check if Cognito is not configured
    if not AUTH_ENABLED:
        return None

    # Allow public routes
    if is_public_route(request.path):
        return None

    # Allow static files
    if request.path.startswith("/static/"):
        return None

    # Check if authenticated
    if not is_authenticated():
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required", "code": "AUTH_REQUIRED"}), 401
        return redirect(url_for("login"))

    return None


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route("/login")
def login():
    """Render the login page."""
    # If already authenticated, redirect to home
    if is_authenticated():
        return redirect(url_for("index"))

    # Pass Cognito config to template
    return render_template(
        "login.html",
        cognito_domain=COGNITO_DOMAIN,
        client_id=COGNITO_CLIENT_ID,
        callback_url=get_callback_url(),
    )


@app.route("/register")
def register():
    """Render the registration page."""
    # If already authenticated, redirect to home
    if is_authenticated():
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/auth/register", methods=["POST"])
def auth_register():
    """Handle user registration form submission."""
    # Collect form data
    form_data = {
        "first_name": request.form.get("first_name", "").strip(),
        "last_name": request.form.get("last_name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "primary_contact": request.form.get("primary_contact", "email"),
        "secondary_email": request.form.get("secondary_email", "").strip(),
        "secondary_phone": request.form.get("secondary_phone", "").strip(),
        "password": request.form.get("password", ""),
        "confirm_password": request.form.get("confirm_password", ""),
        "street_address": request.form.get("street_address", "").strip(),
        "city": request.form.get("city", "").strip(),
        "state": request.form.get("state", "").strip(),
        "postal_code": request.form.get("postal_code", "").strip(),
        "country": request.form.get("country", "").strip(),
        "terms_accepted": request.form.get("terms_accepted") == "on",
        "hipaa_acknowledged": request.form.get("hipaa_acknowledged") == "on",
    }

    # Validate form data
    is_valid, errors = validate_registration_data(form_data)

    if not is_valid:
        # Return to form with errors
        error_message = ". ".join(errors.values())
        return render_template(
            "register.html",
            error=error_message,
            form_data=form_data,
        )

    # Determine username and contact info for Cognito
    primary_contact = form_data["primary_contact"]
    if primary_contact == "email":
        username = form_data["email"]
        email = form_data["email"]
        phone = form_data.get("secondary_phone") or None
    else:
        phone = form_data["phone"]
        username = normalize_phone(phone)
        email = form_data.get("secondary_email") or None

    # Create user in Cognito
    success, user_sub, error_message = create_cognito_user(
        username=username,
        password=form_data["password"],
        email=email,
        phone=phone if phone else None,
        first_name=form_data["first_name"],
        last_name=form_data["last_name"],
    )

    if not success:
        return render_template(
            "register.html",
            error=error_message,
            form_data=form_data,
        )

    # Store user profile in local database
    try:
        store_user_profile(user_sub, form_data)
    except Exception as e:
        print(f"Warning: Failed to store user profile in database: {e}")
        # Continue anyway - user was created in Cognito

    # Redirect to login page with success message
    # User needs to verify their email/phone before logging in
    return render_template(
        "register.html",
        success=f"Account created successfully! Please check your {'email' if primary_contact == 'email' else 'phone'} for a verification code. After verifying, you can sign in and set up MFA.",
    )


def store_user_profile(cognito_sub: str, form_data: dict) -> bool:
    """
    Store user profile data in the local database.

    This stores additional HIPAA-required information that isn't stored in Cognito.
    """
    # For now, we'll use SQLite for local development
    # In production, this would use PostgreSQL via RDS
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if users table has the new columns (for backwards compatibility)
        # This is a simple check - in production, use proper migrations
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        # If the new columns exist, insert with full profile
        if "first_name" in columns:
            cursor.execute("""
                INSERT INTO users (
                    cognito_sub, email, display_name, role,
                    first_name, last_name, phone,
                    street_address, city, state, postal_code, country,
                    terms_accepted_at, hipaa_acknowledged_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                cognito_sub,
                form_data.get("email") or form_data.get("secondary_email"),
                f"{form_data['first_name']} {form_data['last_name']}",
                "viewer",  # Default role
                form_data["first_name"],
                form_data["last_name"],
                form_data.get("phone") or form_data.get("secondary_phone"),
                form_data["street_address"],
                form_data["city"],
                form_data["state"],
                form_data["postal_code"],
                form_data["country"],
                datetime.utcnow().isoformat() if form_data.get("terms_accepted") else None,
                datetime.utcnow().isoformat() if form_data.get("hipaa_acknowledged") else None,
            ))
        else:
            # Fallback for older schema
            cursor.execute("""
                INSERT INTO users (cognito_sub, email, display_name, role)
                VALUES (?, ?, ?, ?)
            """, (
                cognito_sub,
                form_data.get("email") or form_data.get("secondary_email"),
                f"{form_data['first_name']} {form_data['last_name']}",
                "viewer",
            ))

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"Error storing user profile: {e}")
        return False


@app.route("/auth/callback")
def auth_callback():
    """Handle OAuth callback from Cognito."""
    code = request.args.get("code")
    error = request.args.get("error")
    error_description = request.args.get("error_description")

    if error:
        return render_template(
            "login.html",
            error=error_description or error,
            cognito_domain=COGNITO_DOMAIN,
            client_id=COGNITO_CLIENT_ID,
            callback_url=get_callback_url(),
        )

    if not code:
        return redirect(url_for("login"))

    # Exchange code for tokens
    tokens = exchange_code_for_tokens(code, get_callback_url())
    if not tokens:
        return render_template(
            "login.html",
            error="Failed to authenticate. Please try again.",
            cognito_domain=COGNITO_DOMAIN,
            client_id=COGNITO_CLIENT_ID,
            callback_url=get_callback_url(),
        )

    # Set cookies with tokens
    response = make_response(redirect(url_for("index")))

    # Access token cookie (short-lived, used for API calls)
    response.set_cookie(
        "access_token",
        tokens.get("access_token", ""),
        httponly=True,
        secure=request.scheme == "https",
        samesite="Lax",
        max_age=900,  # 15 minutes
    )

    # ID token cookie (contains user info)
    response.set_cookie(
        "id_token",
        tokens.get("id_token", ""),
        httponly=True,
        secure=request.scheme == "https",
        samesite="Lax",
        max_age=900,
    )

    # Refresh token cookie (longer-lived, used to get new access tokens)
    response.set_cookie(
        "refresh_token",
        tokens.get("refresh_token", ""),
        httponly=True,
        secure=request.scheme == "https",
        samesite="Lax",
        max_age=28800,  # 8 hours
    )

    # Log the login event
    # Note: We can't easily log to DB here without the user context
    print(f"LOGIN: User authenticated successfully")

    return response


@app.route("/auth/logout")
def auth_logout():
    """Log out the user."""
    # Clear cookies
    response = make_response(redirect(url_for("login")))
    response.delete_cookie("access_token")
    response.delete_cookie("id_token")
    response.delete_cookie("refresh_token")

    # If Cognito is configured, redirect to Cognito logout
    if COGNITO_DOMAIN:
        logout_url = get_cognito_logout_url(f"{get_base_url()}/login")
        response = make_response(redirect(logout_url))
        response.delete_cookie("access_token")
        response.delete_cookie("id_token")
        response.delete_cookie("refresh_token")

    return response


@app.route("/auth/refresh", methods=["POST"])
def auth_refresh():
    """Refresh the access token using the refresh token."""
    refresh_token_value = request.cookies.get("refresh_token")

    if not refresh_token_value:
        return jsonify({"error": "No refresh token"}), 401

    tokens = refresh_tokens(refresh_token_value)
    if not tokens:
        return jsonify({"error": "Token refresh failed"}), 401

    response = make_response(jsonify({"success": True}))

    # Update access token cookie
    response.set_cookie(
        "access_token",
        tokens.get("access_token", ""),
        httponly=True,
        secure=request.scheme == "https",
        samesite="Lax",
        max_age=900,
    )

    # Update ID token if provided
    if tokens.get("id_token"):
        response.set_cookie(
            "id_token",
            tokens.get("id_token", ""),
            httponly=True,
            secure=request.scheme == "https",
            samesite="Lax",
            max_age=900,
        )

    return response


@app.route("/api/auth/user")
def get_user_info():
    """Get the current authenticated user's information."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    return jsonify({
        "email": user.get("email"),
        "name": user.get("name"),
        "role": user.get("role"),
        "groups": user.get("groups", []),
    })


def get_db_connection():
    """Get SQLite database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_dicom_file(file_path_or_s3_key: str) -> pydicom.Dataset:
    """
    Load a DICOM file from local filesystem or S3.
    Uses local cache for S3 files to avoid repeated downloads.
    """
    if USE_S3:
        # Check local cache first
        cache_path = CACHE_DIR / file_path_or_s3_key.replace("/", "_")

        if cache_path.exists():
            return pydicom.dcmread(cache_path)

        # Download from S3
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=file_path_or_s3_key)
            dicom_bytes = response["Body"].read()

            # Cache locally
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(dicom_bytes)

            return pydicom.dcmread(io.BytesIO(dicom_bytes))
        except Exception as e:
            raise RuntimeError(f"Failed to load from S3: {file_path_or_s3_key} - {e}")
    else:
        # Load from local filesystem
        return pydicom.dcmread(file_path_or_s3_key)


def get_file_path_column():
    """Return the column name for file paths (file_path for local, s3_key for cloud)."""
    return "s3_key" if USE_S3 else "file_path"


def load_volume_cached(study_id: str, series_name: str):
    """Load and cache a 3D volume for a study/series."""
    cache_key = f"{study_id}:{series_name}"

    if cache_key in volume_cache:
        return volume_cache[cache_key]

    conn = get_db_connection()
    cursor = conn.cursor()

    file_col = get_file_path_column()

    cursor.execute(f"""
        SELECT {file_col} as file_path, InstanceNumber, ImagePositionPatient, PixelSpacing, SliceThickness
        FROM dicom_files
        WHERE StudyInstanceUID = ? AND SeriesDescription = ?
        ORDER BY InstanceNumber
    """, (study_id, series_name))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    # Get spacing info
    pixel_spacing = [1.0, 1.0]
    slice_thickness = 1.0

    if rows[0]["PixelSpacing"]:
        try:
            pixel_spacing = json.loads(rows[0]["PixelSpacing"])
        except:
            pass

    if rows[0]["SliceThickness"]:
        slice_thickness = float(rows[0]["SliceThickness"])

    # Load all slices
    slices = []
    raw_slices = []
    for row in rows:
        try:
            dcm = load_dicom_file(row["file_path"])
            pixel_array = dcm.pixel_array.astype(np.float32)
            raw_slices.append(pixel_array.copy())
            slices.append(pixel_array)
        except Exception as e:
            print(f"Error loading {row['file_path']}: {e}")
            continue

    if not slices:
        return None

    # Stack into 3D volume (z, y, x)
    volume = np.stack(slices, axis=0)
    raw_volume = np.stack(raw_slices, axis=0)

    # Normalize
    vmin, vmax = volume.min(), volume.max()
    if vmax > vmin:
        normalized = (volume - vmin) / (vmax - vmin)
    else:
        normalized = np.zeros_like(volume)

    result = {
        "volume": normalized,
        "raw_volume": raw_volume,
        "dimensions": volume.shape,  # (z, y, x)
        "pixel_spacing": pixel_spacing,
        "slice_thickness": slice_thickness,
        "vmin": float(vmin),
        "vmax": float(vmax)
    }

    # Cache (limit to 3 volumes to avoid memory issues)
    if len(volume_cache) >= 3:
        oldest = next(iter(volume_cache))
        del volume_cache[oldest]
    volume_cache[cache_key] = result

    return result


@app.route("/")
def index():
    """Serve the main viewer page."""
    return render_template("viewer.html")


@app.route("/api/studies")
def get_studies():
    """Get list of available studies."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT StudyInstanceUID, StudyDescription, StudyDate,
               COUNT(DISTINCT SeriesDescription) as sequence_count,
               COUNT(*) as slice_count
        FROM dicom_files
        GROUP BY StudyInstanceUID
        ORDER BY StudyDate DESC
    """)
    studies = []
    for row in cursor.fetchall():
        date = row["StudyDate"]
        # Format date as YYYY-MM-DD
        if date and len(date) == 8:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        studies.append({
            "id": row["StudyInstanceUID"],
            "description": row["StudyDescription"],
            "date": date,
            "sequences": row["sequence_count"],
            "slices": row["slice_count"]
        })
    conn.close()
    return jsonify(studies)


@app.route("/api/sequences/<study_id>")
def get_sequences(study_id):
    """Get list of sequences for a specific study."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SeriesDescription, COUNT(*) as slice_count
        FROM dicom_files
        WHERE StudyInstanceUID = ?
        GROUP BY SeriesDescription
        ORDER BY slice_count DESC
    """, (study_id,))
    sequences = [
        {"name": row["SeriesDescription"], "slices": row["slice_count"]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(sequences)


@app.route("/api/volume/<study_id>/<series_name>")
def get_volume(study_id, series_name):
    """
    Get voxel data for a specific MRI sequence within a study.
    Returns downsampled voxel positions and intensities.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    file_col = get_file_path_column()

    # Get all files for this series within the study, ordered by instance number
    cursor.execute(f"""
        SELECT {file_col} as file_path, InstanceNumber, ImagePositionPatient, PixelSpacing, SliceThickness
        FROM dicom_files
        WHERE StudyInstanceUID = ? AND SeriesDescription = ?
        ORDER BY InstanceNumber
    """, (study_id, series_name))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "Series not found"}), 404

    # Get spacing info from first row
    pixel_spacing = [1.0, 1.0]
    slice_thickness = 1.0

    if rows[0]["PixelSpacing"]:
        try:
            pixel_spacing = json.loads(rows[0]["PixelSpacing"])
        except:
            pass

    if rows[0]["SliceThickness"]:
        slice_thickness = float(rows[0]["SliceThickness"])

    # Load DICOM slices and build volume
    slices = []
    for row in rows:
        try:
            dcm = load_dicom_file(row["file_path"])
            pixel_array = dcm.pixel_array.astype(np.float32)
            slices.append(pixel_array)
        except Exception as e:
            print(f"Error loading {row['file_path']}: {e}")
            continue

    if not slices:
        return jsonify({"error": "Could not load any slices"}), 500

    # Stack into 3D volume (z, y, x)
    volume = np.stack(slices, axis=0)

    # Get volume dimensions
    nz, ny, nx = volume.shape

    # Normalize intensity to 0-1 range
    vmin, vmax = volume.min(), volume.max()
    if vmax > vmin:
        volume = (volume - vmin) / (vmax - vmin)

    # Downsample for browser performance
    # Skip every Nth voxel, send ALL voxels (filtering done client-side)
    step = 4  # Sample every 4th voxel
    min_threshold = 0.05  # Only skip very dark background

    voxels = []
    for z in range(0, nz, step):
        for y in range(0, ny, step):
            for x in range(0, nx, step):
                intensity = float(volume[z, y, x])
                if intensity > min_threshold:
                    voxels.append({
                        "x": x - nx // 2,  # Center the volume
                        "y": y - ny // 2,
                        "z": z - nz // 2,
                        "i": round(intensity, 3)
                    })

    # Limit total voxels if still too many
    max_voxels = 150000
    if len(voxels) > max_voxels:
        # Sort by intensity and keep brightest
        voxels.sort(key=lambda v: v["i"], reverse=True)
        voxels = voxels[:max_voxels]

    return jsonify({
        "dimensions": [nx, ny, nz],
        "pixelSpacing": pixel_spacing,
        "sliceThickness": slice_thickness,
        "voxelCount": len(voxels),
        "step": step,
        "voxels": voxels
    })


@app.route("/api/slice/<study_id>/<series_name>/<int:slice_num>")
def get_slice(study_id, series_name, slice_num):
    """
    Get a single 2D slice as pixel intensity array.
    Returns normalized pixel values for canvas rendering.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    file_col = get_file_path_column()

    # Get all files for this series within the study, ordered by instance number
    cursor.execute(f"""
        SELECT {file_col} as file_path, InstanceNumber
        FROM dicom_files
        WHERE StudyInstanceUID = ? AND SeriesDescription = ?
        ORDER BY InstanceNumber
    """, (study_id, series_name))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "Series not found"}), 404

    total_slices = len(rows)

    # Clamp slice number
    slice_num = max(0, min(slice_num, total_slices - 1))

    # Load the specific slice
    try:
        dcm = load_dicom_file(rows[slice_num]["file_path"])
        pixel_array = dcm.pixel_array.astype(np.float32)
    except Exception as e:
        return jsonify({"error": f"Could not load slice: {e}"}), 500

    ny, nx = pixel_array.shape

    # Normalize to 0-255 for canvas rendering
    vmin, vmax = pixel_array.min(), pixel_array.max()
    if vmax > vmin:
        normalized = ((pixel_array - vmin) / (vmax - vmin) * 255).astype(np.uint8)
    else:
        normalized = np.zeros_like(pixel_array, dtype=np.uint8)

    # Flatten to list for JSON
    pixels = normalized.flatten().tolist()

    return jsonify({
        "width": nx,
        "height": ny,
        "pixels": pixels,
        "sliceNum": slice_num,
        "totalSlices": total_slices
    })


@app.route("/api/orthoslice/<study_id>/<series_name>/<plane>/<int:index>")
def get_orthoslice(study_id, series_name, plane, index):
    """
    Get a 2D slice from any orthogonal plane.
    plane: 'axial' (Z), 'sagittal' (X), or 'coronal' (Y)
    For sagittal/coronal, scales Z axis to account for slice thickness vs pixel spacing.
    """
    vol_data = load_volume_cached(study_id, series_name)
    if vol_data is None:
        return jsonify({"error": "Volume not found"}), 404

    volume = vol_data["volume"]
    nz, ny, nx = vol_data["dimensions"]
    pixel_spacing = vol_data["pixel_spacing"]
    slice_thickness = vol_data["slice_thickness"]

    # Calculate Z scale factor (slice thickness / pixel spacing)
    z_scale = slice_thickness / pixel_spacing[0] if pixel_spacing[0] > 0 else 1.0

    if plane == "axial":
        # XY plane at Z=index - no scaling needed
        index = max(0, min(index, nz - 1))
        slice_2d = volume[index, :, :]
        width, height = nx, ny
        total = nz
        # No resize needed for axial
        normalized = (slice_2d * 255).astype(np.uint8)
    elif plane == "sagittal":
        # YZ plane at X=index
        index = max(0, min(index, nx - 1))
        slice_2d = volume[:, :, index]  # shape: (nz, ny)
        # Scale Z dimension to correct aspect ratio
        from scipy.ndimage import zoom
        slice_scaled = zoom(slice_2d, (z_scale, 1.0), order=1)
        # Flip vertically so superior (top of head) is at top of image
        slice_scaled = np.flipud(slice_scaled)
        # Use actual zoomed dimensions (zoom may round differently)
        height, width = slice_scaled.shape  # (scaled_nz, ny)
        total = nx
        normalized = (slice_scaled * 255).astype(np.uint8)
    elif plane == "coronal":
        # XZ plane at Y=index
        index = max(0, min(index, ny - 1))
        slice_2d = volume[:, index, :]  # shape: (nz, nx)
        # Scale Z dimension to correct aspect ratio
        from scipy.ndimage import zoom
        slice_scaled = zoom(slice_2d, (z_scale, 1.0), order=1)
        # Flip vertically so superior (top of head) is at top of image
        slice_scaled = np.flipud(slice_scaled)
        # Use actual zoomed dimensions
        height, width = slice_scaled.shape  # (scaled_nz, nx)
        total = ny
        normalized = (slice_scaled * 255).astype(np.uint8)
    else:
        return jsonify({"error": "Invalid plane"}), 400

    pixels = normalized.flatten().tolist()

    return jsonify({
        "width": width,
        "height": height,
        "pixels": pixels,
        "sliceIndex": index,
        "totalSlices": total,
        "plane": plane,
        "zScale": z_scale
    })


@app.route("/api/voxel-metadata/<study_id>/<series_name>/<int:x>/<int:y>/<int:z>")
def get_voxel_metadata(study_id, series_name, x, y, z):
    """
    Get comprehensive metadata for a specific voxel location.
    Returns slice metadata + computed voxel values.
    """
    vol_data = load_volume_cached(study_id, series_name)
    if vol_data is None:
        return jsonify({"error": "Volume not found"}), 404

    nz, ny, nx = vol_data["dimensions"]

    # Clamp coordinates
    x = max(0, min(x, nx - 1))
    y = max(0, min(y, ny - 1))
    z = max(0, min(z, nz - 1))

    # Get voxel values
    raw_value = float(vol_data["raw_volume"][z, y, x])
    norm_value = float(vol_data["volume"][z, y, x])

    # Calculate world position
    pixel_spacing = vol_data["pixel_spacing"]
    slice_thickness = vol_data["slice_thickness"]

    # Get metadata from the database for this slice
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM dicom_files
        WHERE StudyInstanceUID = ? AND SeriesDescription = ?
        ORDER BY InstanceNumber
        LIMIT 1 OFFSET ?
    """, (study_id, series_name, z))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Slice metadata not found"}), 404

    # Parse ImagePositionPatient for world coordinates
    world_pos = [0, 0, 0]
    if row["ImagePositionPatient"]:
        try:
            origin = json.loads(row["ImagePositionPatient"])
            world_pos = [
                origin[0] + x * pixel_spacing[1],
                origin[1] + y * pixel_spacing[0],
                origin[2]
            ]
        except:
            pass

    # Build comprehensive metadata response
    metadata = {
        # Voxel info
        "voxel": {
            "x": x, "y": y, "z": z,
            "rawValue": raw_value,
            "normValue": round(norm_value, 4),
            "worldPos": [round(p, 2) for p in world_pos]
        },
        # Volume info
        "volume": {
            "dimensions": [nx, ny, nz],
            "pixelSpacing": pixel_spacing,
            "sliceThickness": slice_thickness,
            "valueRange": [vol_data["vmin"], vol_data["vmax"]]
        },
        # MRI Parameters
        "mri": {
            "TR": row["RepetitionTime"],
            "TE": row["EchoTime"],
            "TI": row["InversionTime"],
            "flipAngle": row["FlipAngle"],
            "fieldStrength": row["MagneticFieldStrength"],
            "scanningSequence": row["ScanningSequence"],
            "sequenceVariant": row["SequenceVariant"],
            "acquisitionType": row["MRAcquisitionType"]
        },
        # Spatial
        "spatial": {
            "sliceLocation": row["SliceLocation"],
            "sliceThickness": row["SliceThickness"],
            "imagePosition": row["ImagePositionPatient"],
            "imageOrientation": row["ImageOrientationPatient"]
        },
        # Study/Series
        "study": {
            "description": row["StudyDescription"],
            "date": row["StudyDate"],
            "time": row["StudyTime"]
        },
        "series": {
            "description": row["SeriesDescription"],
            "number": row["SeriesNumber"],
            "modality": row["Modality"]
        },
        # Instance
        "instance": {
            "number": row["InstanceNumber"],
            "acquisitionDate": row["AcquisitionDate"],
            "acquisitionTime": row["AcquisitionTime"]
        },
        # Equipment
        "equipment": {
            "manufacturer": row["Manufacturer"],
            "model": row["ManufacturerModelName"],
            "station": row["StationName"],
            "institution": row["InstitutionName"]
        },
        # Display
        "display": {
            "windowCenter": row["WindowCenter"],
            "windowWidth": row["WindowWidth"]
        }
    }

    return jsonify(metadata)


@app.route("/api/volume-info/<study_id>/<series_name>")
def get_volume_info(study_id, series_name):
    """Get volume dimensions and spacing without loading full volume data."""
    vol_data = load_volume_cached(study_id, series_name)
    if vol_data is None:
        return jsonify({"error": "Volume not found"}), 404

    nz, ny, nx = vol_data["dimensions"]
    return jsonify({
        "dimensions": {"x": nx, "y": ny, "z": nz},
        "pixelSpacing": vol_data["pixel_spacing"],
        "sliceThickness": vol_data["slice_thickness"]
    })


@app.route("/api/health")
def health_check():
    """Health check endpoint for load balancers."""
    return jsonify({"status": "healthy", "storage": "s3" if USE_S3 else "local"})


if __name__ == "__main__":
    print(f"Storage mode: {'S3 (' + S3_BUCKET_NAME + ')' if USE_S3 else 'Local'}")
    print(f"Database: {DB_PATH}")
    print("Starting server at http://127.0.0.1:5000")
    app.run(debug=True, host="127.0.0.1", port=5000)
