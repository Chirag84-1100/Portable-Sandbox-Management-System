"""
Authentication and Authorization Helpers for Flask API.
Provides:
- Session-based user resolution (get_current_user)
- Route protection decorators (@login_required, @admin_required)
- Strict resource ownership verification to prevent cross-tenant access
"""

from functools import wraps
from typing import Any, Dict, Optional, Tuple
from flask import jsonify, session

from app.database import get_execution_run_by_id, get_sandbox_by_id, get_user_by_id


def get_current_user(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves the currently authenticated user from session.
    Verifies that the session user still exists in the database.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = get_user_by_id(user_id, db_path=db_path)
    if not user:
        # Stale session, user deleted
        session.clear()
        return None

    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


def login_required(f):
    """Decorator requiring active session authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({
                "success": False,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Authentication required. Please log in."
                }
            }), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator requiring admin role privileges."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({
                "success": False,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Authentication required. Please log in."
                }
            }), 401

        if session.get("role") != "admin":
            return jsonify({
                "success": False,
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Administrative privileges required."
                }
            }), 403
        return f(*args, **kwargs)
    return decorated_function


def verify_sandbox_ownership(
    sandbox_id: int,
    user: Dict[str, Any],
    db_path: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], int]:
    """
    Verifies that the requested sandbox exists and belongs to the authenticated user.
    Admins can bypass ownership checks.
    Returns (sandbox_dict, error_dict, status_code).
    If authorized: returns (sandbox_dict, None, 200).
    """
    sandbox = get_sandbox_by_id(sandbox_id, db_path=db_path)
    if not sandbox:
        return None, {
            "code": "NOT_FOUND",
            "message": f"Sandbox with ID {sandbox_id} does not exist."
        }, 404

    if sandbox["user_id"] != user["id"] and user.get("role") != "admin":
        return None, {
            "code": "FORBIDDEN",
            "message": "Access denied. You do not own this sandbox."
        }, 403

    return sandbox, None, 200


def verify_execution_ownership(
    run_id: int,
    user: Dict[str, Any],
    db_path: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], int]:
    """
    Verifies that the requested execution run exists and its parent sandbox belongs to the user.
    Returns (run_dict, error_dict, status_code).
    """
    run_record = get_execution_run_by_id(run_id, db_path=db_path)
    if not run_record:
        return None, {
            "code": "NOT_FOUND",
            "message": f"Execution run with ID {run_id} does not exist."
        }, 404

    sandbox_id = run_record["sandbox_id"]
    sandbox, err, status = verify_sandbox_ownership(sandbox_id, user, db_path=db_path)
    if err:
        return None, err, status

    return run_record, None, 200
