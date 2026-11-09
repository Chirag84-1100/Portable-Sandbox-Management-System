"""
Web Blueprint for Portable Sandbox Management System.
Serves Jinja2 templates and user-facing HTML pages.
Interacts with session for page-level access control.
"""

from functools import wraps
from flask import Blueprint, redirect, render_template, session, url_for

web_bp = Blueprint("web", __name__)


def web_login_required(f):
    """Decorator redirecting unauthenticated browser sessions to the login page."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("web.login_page"))
        return f(*args, **kwargs)
    return decorated_function


@web_bp.route("/")
def index():
    """Root route: directs users to dashboard or login based on active session."""
    if "user_id" in session:
        return redirect(url_for("web.dashboard_page"))
    return redirect(url_for("web.login_page"))


@web_bp.route("/login")
def login_page():
    """Renders user authentication login screen."""
    if "user_id" in session:
        return redirect(url_for("web.dashboard_page"))
    return render_template("login.html")


@web_bp.route("/register")
def register_page():
    """Renders public registration screen. Enforces role='user' by design."""
    if "user_id" in session:
        return redirect(url_for("web.dashboard_page"))
    return render_template("register.html")


@web_bp.route("/logout")
def logout_page():
    """Terminates session and redirects to login."""
    session.clear()
    return redirect(url_for("web.login_page"))


@web_bp.route("/dashboard")
@web_login_required
def dashboard_page():
    """Renders primary operational dashboard."""
    return render_template("dashboard.html", active_nav="dashboard")


@web_bp.route("/sandboxes")
@web_login_required
def sandboxes_page():
    """Renders dedicated sandbox workspaces management page."""
    return render_template("sandboxes.html", active_nav="sandboxes")


@web_bp.route("/sandboxes/<int:sandbox_id>")
@web_login_required
def sandbox_detail_page(sandbox_id: int):
    """Renders sandbox workspace detail and process execution interface."""
    return render_template("sandbox_detail.html", sandbox_id=sandbox_id, active_nav="sandboxes")


@web_bp.route("/monitor")
@web_login_required
def monitor_page():
    """Renders real-time OS process monitoring and telemetry dashboard."""
    return render_template("monitor.html", active_nav="monitor")


@web_bp.route("/activity")
@web_login_required
def activity_page():
    """Renders system audit trail and execution history logs."""
    return render_template("activity.html", active_nav="activity")


@web_bp.route("/settings")
@web_login_required
def settings_page():
    """Renders system configuration and environment settings view."""
    return render_template("settings.html", active_nav="settings")
