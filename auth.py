"""
OpenRadiomics - Authentication Module
HIPAA-compliant authentication using AWS Cognito.

Provides:
- JWT validation using Cognito JWKS
- @requires_auth decorator for protected routes
- @requires_role decorator for RBAC
- Audit logging for all access
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from functools import wraps
from typing import Optional

import requests
from flask import g, redirect, request, url_for, jsonify
from jose import jwt, JWTError

# Environment configuration
COGNITO_REGION = os.environ.get("AWS_REGION", "us-east-1")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "")

# JWKS cache
_jwks_cache = None
_jwks_cache_time = 0
JWKS_CACHE_TTL = 3600  # 1 hour

# Role hierarchy (higher index = more privileges)
ROLE_HIERARCHY = {
    "viewer": 0,
    "researcher": 1,
    "clinician": 2,
    "admin": 3
}

# Public routes that don't require authentication
PUBLIC_ROUTES = {
    "/login",
    "/register",
    "/auth/callback",
    "/auth/logout",
    "/api/health",
    "/static",
}


def get_jwks_url() -> str:
    """Get the JWKS URL for the Cognito User Pool."""
    return f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"


def get_jwks() -> dict:
    """
    Fetch and cache the JWKS from Cognito.
    Caches for 1 hour to avoid excessive requests.
    """
    global _jwks_cache, _jwks_cache_time

    now = time.time()
    if _jwks_cache and (now - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    try:
        response = requests.get(get_jwks_url(), timeout=5)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = now
        return _jwks_cache
    except Exception as e:
        print(f"Error fetching JWKS: {e}")
        if _jwks_cache:
            return _jwks_cache
        raise


def get_signing_key(token: str) -> Optional[dict]:
    """Get the signing key for a token from JWKS."""
    try:
        headers = jwt.get_unverified_headers(token)
        kid = headers.get("kid")
        if not kid:
            return None

        jwks = get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None
    except Exception:
        return None


def validate_token(token: str) -> Optional[dict]:
    """
    Validate a JWT token from Cognito.
    Returns the decoded claims if valid, None otherwise.
    """
    if not token:
        return None

    if not COGNITO_USER_POOL_ID or not COGNITO_CLIENT_ID:
        print("Warning: Cognito not configured, authentication disabled")
        return None

    try:
        # Get the signing key
        signing_key = get_signing_key(token)
        if not signing_key:
            print("Could not find signing key for token")
            return None

        # Verify the token
        issuer = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"

        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=COGNITO_CLIENT_ID,
            issuer=issuer,
            options={
                "verify_at_hash": False,  # Access tokens don't have at_hash
                "require_exp": True,
                "require_iat": True,
            }
        )

        # Verify token_use (should be 'access' or 'id')
        token_use = claims.get("token_use")
        if token_use not in ("access", "id"):
            print(f"Invalid token_use: {token_use}")
            return None

        return claims

    except JWTError as e:
        print(f"JWT validation error: {e}")
        return None
    except Exception as e:
        print(f"Token validation error: {e}")
        return None


def get_token_from_request() -> Optional[str]:
    """Extract the access token from the request."""
    # Check Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    # Check cookie
    return request.cookies.get("access_token")


def get_current_user() -> Optional[dict]:
    """
    Get the current authenticated user from the request.
    Returns user info dict or None if not authenticated.
    """
    if hasattr(g, "current_user"):
        return g.current_user

    token = get_token_from_request()
    if not token:
        return None

    claims = validate_token(token)
    if not claims:
        return None

    # Build user info from claims
    user = {
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "name": claims.get("name") or claims.get("email", "").split("@")[0],
        "groups": claims.get("cognito:groups", []),
        "token_use": claims.get("token_use"),
    }

    # Determine role from groups (highest privilege wins)
    role = "viewer"  # Default role
    max_level = -1
    for group in user["groups"]:
        level = ROLE_HIERARCHY.get(group, -1)
        if level > max_level:
            max_level = level
            role = group
    user["role"] = role

    # Cache in request context
    g.current_user = user
    return user


def get_user_role() -> str:
    """Get the current user's role."""
    user = get_current_user()
    return user.get("role", "viewer") if user else "viewer"


def is_authenticated() -> bool:
    """Check if the current request is authenticated."""
    return get_current_user() is not None


def requires_auth(f):
    """
    Decorator to require authentication for a route.
    Redirects to login page for web requests, returns 401 for API requests.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def requires_role(min_role: str):
    """
    Decorator to require a minimum role for a route.
    Checks role hierarchy: viewer < researcher < clinician < admin
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Authentication required"}), 401
                return redirect(url_for("login"))

            user_level = ROLE_HIERARCHY.get(user.get("role", "viewer"), 0)
            required_level = ROLE_HIERARCHY.get(min_role, 0)

            if user_level < required_level:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Insufficient permissions"}), 403
                return jsonify({"error": "You do not have permission to access this resource"}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def log_audit(
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    response_status: Optional[int] = None,
    db_connection=None
):
    """
    Log an access event to the audit_log table.

    Args:
        action: The action being performed (e.g., 'view_study', 'login', 'logout')
        resource_type: Type of resource accessed (e.g., 'study', 'series')
        resource_id: ID of the resource
        response_status: HTTP response status code
        db_connection: Database connection (if None, tries to get from context)
    """
    user = get_current_user()

    # Get user_id from database if user is authenticated
    user_id = None
    if user and db_connection:
        try:
            cursor = db_connection.cursor()
            cursor.execute(
                "SELECT id FROM users WHERE cognito_sub = %s",
                (user.get("sub"),)
            )
            result = cursor.fetchone()
            if result:
                user_id = result[0]
        except Exception as e:
            print(f"Error looking up user_id for audit: {e}")

    # Get client IP
    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip_address and "," in ip_address:
        ip_address = ip_address.split(",")[0].strip()

    if db_connection:
        try:
            cursor = db_connection.cursor()
            cursor.execute(
                """
                INSERT INTO audit_log
                    (user_id, action, resource_type, resource_id, ip_address, request_path, response_status)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, action, resource_type, resource_id, ip_address, request.path, response_status)
            )
            db_connection.commit()
        except Exception as e:
            print(f"Error writing audit log: {e}")
    else:
        # Fallback to console logging if no DB connection
        print(f"AUDIT: {datetime.utcnow().isoformat()} | user={user.get('email') if user else 'anonymous'} | action={action} | resource={resource_type}:{resource_id} | path={request.path} | ip={ip_address}")


def is_public_route(path: str) -> bool:
    """Check if a route is public (doesn't require authentication)."""
    for public_path in PUBLIC_ROUTES:
        if path == public_path or path.startswith(public_path + "/"):
            return True
    return False


def get_cognito_login_url(redirect_uri: str) -> str:
    """Build the Cognito hosted UI login URL."""
    return (
        f"https://{COGNITO_DOMAIN}/login?"
        f"client_id={COGNITO_CLIENT_ID}&"
        f"response_type=code&"
        f"scope=email+openid+profile&"
        f"redirect_uri={redirect_uri}"
    )


def get_cognito_logout_url(redirect_uri: str) -> str:
    """Build the Cognito logout URL."""
    return (
        f"https://{COGNITO_DOMAIN}/logout?"
        f"client_id={COGNITO_CLIENT_ID}&"
        f"logout_uri={redirect_uri}"
    )


def get_cognito_signup_url(redirect_uri: str) -> str:
    """Build the Cognito hosted UI signup URL."""
    return (
        f"https://{COGNITO_DOMAIN}/signup?"
        f"client_id={COGNITO_CLIENT_ID}&"
        f"response_type=code&"
        f"scope=email+openid+profile&"
        f"redirect_uri={redirect_uri}"
    )


def exchange_code_for_tokens(code: str, redirect_uri: str) -> Optional[dict]:
    """
    Exchange an authorization code for tokens.
    Returns dict with access_token, id_token, refresh_token, or None on error.
    """
    token_url = f"https://{COGNITO_DOMAIN}/oauth2/token"

    try:
        response = requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": COGNITO_CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10
        )

        if response.status_code != 200:
            print(f"Token exchange failed: {response.status_code} - {response.text}")
            return None

        return response.json()

    except Exception as e:
        print(f"Error exchanging code for tokens: {e}")
        return None


def refresh_tokens(refresh_token: str) -> Optional[dict]:
    """
    Use a refresh token to get new access/id tokens.
    Returns dict with new tokens, or None on error.
    """
    token_url = f"https://{COGNITO_DOMAIN}/oauth2/token"

    try:
        response = requests.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": COGNITO_CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10
        )

        if response.status_code != 200:
            print(f"Token refresh failed: {response.status_code} - {response.text}")
            return None

        return response.json()

    except Exception as e:
        print(f"Error refreshing tokens: {e}")
        return None


def ensure_user_in_db(user: dict, db_connection) -> Optional[int]:
    """
    Ensure the authenticated user exists in the local users table.
    Creates the user if they don't exist.
    Returns the user's database ID.
    """
    if not user or not db_connection:
        return None

    try:
        cursor = db_connection.cursor()

        # Check if user exists
        cursor.execute(
            "SELECT id FROM users WHERE cognito_sub = %s",
            (user.get("sub"),)
        )
        result = cursor.fetchone()

        if result:
            # Update last_login
            cursor.execute(
                "UPDATE users SET last_login = NOW() WHERE id = %s",
                (result[0],)
            )
            db_connection.commit()
            return result[0]

        # Create new user
        cursor.execute(
            """
            INSERT INTO users (cognito_sub, email, display_name, role, last_login)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (
                user.get("sub"),
                user.get("email"),
                user.get("name"),
                user.get("role", "viewer")
            )
        )
        result = cursor.fetchone()
        db_connection.commit()

        return result[0] if result else None

    except Exception as e:
        print(f"Error ensuring user in database: {e}")
        db_connection.rollback()
        return None
