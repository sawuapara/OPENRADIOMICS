#!/usr/bin/env python3
"""
3D Voxel MRI Viewer - Flask Backend
Serves MRI volume data to Three.js frontend for 3D visualization.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from functools import lru_cache

import numpy as np
import pydicom
from flask import Flask, jsonify, render_template

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "brain_inventory.db"

# Volume cache for orthogonal slicing
volume_cache = {}


def get_db_connection():
    """Get SQLite database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_volume_cached(study_id: str, series_name: str):
    """Load and cache a 3D volume for a study/series."""
    cache_key = f"{study_id}:{series_name}"

    if cache_key in volume_cache:
        return volume_cache[cache_key]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT file_path, InstanceNumber, ImagePositionPatient, PixelSpacing, SliceThickness
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
            dcm = pydicom.dcmread(row["file_path"])
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

    # Get all files for this series within the study, ordered by instance number
    cursor.execute("""
        SELECT file_path, InstanceNumber, ImagePositionPatient, PixelSpacing, SliceThickness
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
            dcm = pydicom.dcmread(row["file_path"])
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

    # Get all files for this series within the study, ordered by instance number
    cursor.execute("""
        SELECT file_path, InstanceNumber
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
        dcm = pydicom.dcmread(rows[slice_num]["file_path"])
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
        scaled_nz = int(nz * z_scale)
        # Use scipy or numpy to resize
        from scipy.ndimage import zoom
        slice_scaled = zoom(slice_2d, (z_scale, 1.0), order=1)
        width, height = ny, scaled_nz
        total = nx
        normalized = (slice_scaled * 255).astype(np.uint8)
    elif plane == "coronal":
        # XZ plane at Y=index
        index = max(0, min(index, ny - 1))
        slice_2d = volume[:, index, :]  # shape: (nz, nx)
        # Scale Z dimension to correct aspect ratio
        scaled_nz = int(nz * z_scale)
        from scipy.ndimage import zoom
        slice_scaled = zoom(slice_2d, (z_scale, 1.0), order=1)
        width, height = nx, scaled_nz
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


if __name__ == "__main__":
    print(f"Database: {DB_PATH}")
    print("Starting server at http://127.0.0.1:5000")
    app.run(debug=True, host="127.0.0.1", port=5000)
