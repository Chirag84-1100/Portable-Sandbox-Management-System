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

# =========================
# OS LAB AND DBMS LAB ROUTES
# =========================

import json
from threading import Thread
from flask import request

from app.os_lab.scheduling import fcfs, sjf, round_robin
from app.os_lab.scheduling import validate_processes
from app.os_lab.memory import allocate_memory
from app.os_lab.deadlock import bankers_algorithm
from app.os_lab.synchronization import BoundedBuffer
from app.os_lab.ipc import pipe_communication
from app.dbms_lab.demonstrations import (
    create_demo_database,
    execute_dbms_demonstration,
)


@web_bp.route("/os-lab", methods=["GET", "POST"])
@web_login_required
def os_lab_page():
    result = None
    error = None
    selected_module = ""
    input_json = ""

    if request.method == "POST":
        selected_module = request.form.get("module", "")
        input_json = request.form.get("payload", "")

        try:
            data = json.loads(input_json or "{}")

            if selected_module == "scheduling":
                validate_processes(data["processes"])
                algorithm = data.get("algorithm", "fcfs")

                if algorithm == "fcfs":
                    result = fcfs(data["processes"])
                elif algorithm == "sjf":
                    result = sjf(data["processes"])
                elif algorithm == "round_robin":
                    result = round_robin(
                        data["processes"], int(data.get("quantum", 2))
                    )
                else:
                    raise ValueError("Unknown scheduling algorithm.")

            elif selected_module == "memory":
                result = allocate_memory(
                    data["blocks"],
                    data["processes"],
                    data.get("strategy", "first_fit"),
                )

            elif selected_module == "deadlock":
                result = bankers_algorithm(
                    data["available"],
                    data["allocation"],
                    data["maximum"],
                )

            elif selected_module == "synchronization":
                buffer = BoundedBuffer(int(data.get("capacity", 3)))
                items = data.get("items", [1, 2, 3, 4, 5])
                consumed = []

                def producer():
                    for item in items:
                        buffer.produce(item)

                def consumer():
                    for _ in items:
                        consumed.append(buffer.consume())

                p = Thread(target=producer)
                c = Thread(target=consumer)
                p.start()
                c.start()
                p.join()
                c.join()

                result = {
                    "consumed_items": consumed,
                    "buffer_status": buffer.get_status(),
                }

            elif selected_module == "ipc":
                result = pipe_communication(
                    str(data.get("message", "Hello from Parent Process!"))
                )

            else:
                raise ValueError("Select a valid OS demonstration.")

        except Exception as exc:
            error = str(exc)

    return render_template(
        "os_lab.html",
        active_nav="os_lab",
        result=result,
        error=error,
        selected_module=selected_module,
        input_json=input_json,
    )


@web_bp.route("/dbms-lab", methods=["GET", "POST"])
@web_login_required
def dbms_lab_page():
    result = None
    error = None
    selected_module = ""

    if request.method == "POST":
        selected_module = request.form.get("module", "")
        db = None

        try:
            result = execute_dbms_demonstration(selected_module)
        except Exception as exc:
            error = str(exc)

    return render_template(
        "dbms_lab.html",
        active_nav="dbms_lab",
        result=result,
        error=error,
        selected_module=selected_module,
    )
