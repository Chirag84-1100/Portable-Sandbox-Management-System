import sqlite3
import sys
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from flask import Blueprint, current_app, jsonify, request, session

from app.auth import (
    admin_required,
    get_current_user,
    login_required,
    verify_execution_ownership,
    verify_sandbox_ownership,
)
from app.database import (
    create_sandbox,
    create_user,
    delete_sandbox,
    get_execution_run_by_id,
    get_metrics_for_run,
    get_run_resource_analytics,
    get_sandbox_analytics,
    get_sandbox_by_id,
    get_user_by_username,
    get_user_dashboard_summary,
    list_execution_runs_for_sandbox,
    list_recent_activity,
    list_sandboxes_for_user,
    log_activity,
    update_execution_run,
    update_sandbox,
    verify_user,
)
from app.monitor import get_host_system_stats
from app.sandbox import (
    ensure_sandbox_dir,
    execute_sync,
    get_or_create_default_sandbox,
    registry,
    spawn_process,
    stop_execution,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")

def json_success(data: Any = None, message: Optional[str] = None, status_code: int = 200):
    """Formats standardized successful JSON response."""
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    if message is not None:
        payload["message"] = message
    return jsonify(payload), status_code


def json_error(message: str, code: str = "BAD_REQUEST", status_code: int = 400, details: Any = None):
    """Formats standardized error JSON response."""
    payload = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details is not None:
        payload["error"]["details"] = details
    return jsonify(payload), status_code


def get_db_path() -> Optional[str]:
    """Retrieves configured SQLite database path from active Flask application context."""
    return current_app.config.get("DATABASE_PATH")


# ==========================================
# 1. AUTHENTICATION ENDPOINTS
# ==========================================

@api_bp.route("/auth/register", methods=["POST"])
def register():
    """
    Public registration endpoint.
    SECURITY REQUIREMENT:
    Always assigns role='user'. Any client-supplied 'role' field is strictly ignored.
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or len(username) < 3:
        return json_error("Username must be at least 3 characters long.", "INVALID_INPUT", 400)

    if not password or len(password) < 6:
        return json_error("Password must be at least 6 characters long.", "INVALID_INPUT", 400)

    db_path = get_db_path()

    # Check for existing username (case-insensitive)
    existing = get_user_by_username(username, db_path=db_path)
    if existing:
        return json_error(f"Username '{username}' is already taken.", "CONFLICT", 409)

    try:
        # Enforce 'user' role regardless of request payload
        user_id = create_user(username=username, password=password, role="user", db_path=db_path)
        log_activity(
            action="USER_REGISTER",
            user_id=user_id,
            details=f"New user registered: {username}",
            db_path=db_path
        )
        return json_success(
            data={"user_id": user_id, "username": username, "role": "user"},
            message="User registration successful.",
            status_code=201
        )
    except sqlite3.IntegrityError:
        return json_error(f"Username '{username}' is already taken.", "CONFLICT", 409)
    except Exception as e:
        return json_error(f"Registration failed: {str(e)}", "SERVER_ERROR", 500)


@api_bp.route("/auth/login", methods=["POST"])
def login():
    """Authenticates credentials and establishes a session."""
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return json_error("Username and password are required.", "INVALID_INPUT", 400)

    db_path = get_db_path()
    user = verify_user(username=username, password=password, db_path=db_path)

    if not user:
        return json_error("Invalid username or password.", "UNAUTHORIZED", 401)

    # Initialize session
    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session.permanent = True

    log_activity(
        action="USER_LOGIN",
        user_id=user["id"],
        details=f"User {user['username']} logged in",
        db_path=db_path
    )

    return json_success(
        data={
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
            }
        },
        message="Login successful."
    )


@api_bp.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    """Terminates user session."""
    user_id = session.get("user_id")
    log_activity(action="USER_LOGOUT", user_id=user_id, details="User logged out", db_path=get_db_path())
    session.clear()
    return json_success(message="Logged out successfully.")


@api_bp.route("/auth/me", methods=["GET"])
@login_required
def get_profile():
    """Returns authenticated user identity."""
    user = get_current_user(db_path=get_db_path())
    if not user:
        return json_error("User session expired or invalid.", "UNAUTHORIZED", 401)
    return json_success(data={"user": user})


# ==========================================
# 2. SANDBOX MANAGEMENT ENDPOINTS
# ==========================================

@api_bp.route("/sandboxes", methods=["POST"])
@login_required
def create_sandbox_endpoint():
    """Creates a new sandbox workspace record and filesystem directory."""
    user = get_current_user(db_path=get_db_path())
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    working_dir = data.get("working_dir")

    if not name:
        return json_error("Sandbox name is required.", "INVALID_INPUT", 400)

    db_path = get_db_path()

    # Check for duplicate sandbox name for this user
    user_sandboxes = list_sandboxes_for_user(user["id"], db_path=db_path)
    if any(sb["name"].lower() == name.lower() for sb in user_sandboxes):
        return json_error(f"You already have a sandbox named '{name}'.", "CONFLICT", 409)

    try:
        sandbox_id = create_sandbox(
            user_id=user["id"],
            name=name,
            description=description,
            working_dir=working_dir,
            db_path=db_path
        )
        sandbox = get_sandbox_by_id(sandbox_id, db_path=db_path)
        # Ensure physical directory exists
        if sandbox:
            ensure_sandbox_dir(sandbox["working_dir"])

        log_activity(
            action="SANDBOX_CREATE",
            user_id=user["id"],
            details=f"Created sandbox '{name}' (ID {sandbox_id})",
            db_path=db_path
        )
        return json_success(data=sandbox, message="Sandbox created successfully.", status_code=201)

    except ValueError as e:
        return json_error(str(e), "INVALID_PATH", 400)
    except sqlite3.IntegrityError:
        return json_error(f"You already have a sandbox named '{name}'.", "CONFLICT", 409)
    except Exception as e:
        return json_error(f"Failed to create sandbox: {str(e)}", "SERVER_ERROR", 500)


@api_bp.route("/sandboxes", methods=["GET"])
@login_required
def list_sandboxes_endpoint():
    """Lists sandboxes for the authenticated user (admins can pass ?all=true)."""
    user = get_current_user(db_path=get_db_path())
    db_path = get_db_path()

    sandboxes = list_sandboxes_for_user(user["id"], db_path=db_path)
    return json_success(data=sandboxes)


@api_bp.route("/sandboxes/<int:sandbox_id>", methods=["GET"])
@login_required
def get_sandbox_endpoint(sandbox_id: int):
    """Retrieves details of a specific sandbox."""
    user = get_current_user(db_path=get_db_path())
    sandbox, err, status = verify_sandbox_ownership(sandbox_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    return json_success(data=sandbox)


@api_bp.route("/sandboxes/<int:sandbox_id>", methods=["PUT"])
@login_required
def update_sandbox_endpoint(sandbox_id: int):
    """Updates a sandbox's name, description, or active status."""
    user = get_current_user(db_path=get_db_path())
    sandbox, err, status = verify_sandbox_ownership(sandbox_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    data = request.get_json(silent=True) or {}
    name = data.get("name")
    description = data.get("description")
    is_active = data.get("is_active")

    if name is not None:
        name = str(name).strip()
        if not name:
            return json_error("Sandbox name cannot be empty.", "INVALID_INPUT", 400)

    db_path = get_db_path()
    try:
        updated = update_sandbox(
            sandbox_id=sandbox_id,
            name=name,
            description=description,
            is_active=is_active,
            db_path=db_path
        )
        if not updated:
            return json_error("No fields updated.", "INVALID_INPUT", 400)

        updated_sandbox = get_sandbox_by_id(sandbox_id, db_path=db_path)
        log_activity(
            action="SANDBOX_UPDATE",
            user_id=user["id"],
            details=f"Updated sandbox {sandbox_id}",
            db_path=db_path
        )
        return json_success(data=updated_sandbox, message="Sandbox updated successfully.")

    except sqlite3.IntegrityError:
        return json_error("A sandbox with this name already exists.", "CONFLICT", 409)


@api_bp.route("/sandboxes/<int:sandbox_id>", methods=["DELETE"])
@login_required
def delete_sandbox_endpoint(sandbox_id: int):
    """Deletes a sandbox. Database cascade removes all associated execution runs and metrics."""
    user = get_current_user(db_path=get_db_path())
    sandbox, err, status = verify_sandbox_ownership(sandbox_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    db_path = get_db_path()
    delete_sandbox(sandbox_id, db_path=db_path)
    log_activity(
        action="SANDBOX_DELETE",
        user_id=user["id"],
        details=f"Deleted sandbox '{sandbox['name']}' (ID {sandbox_id})",
        db_path=db_path
    )
    return json_success(message="Sandbox deleted successfully.")


@api_bp.route("/sandboxes/<int:sandbox_id>/analytics", methods=["GET"])
@login_required
def sandbox_analytics_endpoint(sandbox_id: int):
    """Returns analytical aggregate stats for a specific sandbox."""
    user = get_current_user(db_path=get_db_path())
    sandbox, err, status = verify_sandbox_ownership(sandbox_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    analytics = get_sandbox_analytics(sandbox_id, db_path=get_db_path())
    return json_success(data=analytics)


# ==========================================
# 3. PROCESS & EXECUTION ENDPOINTS
# ==========================================

@api_bp.route("/sandboxes/<int:sandbox_id>/execute", methods=["POST"])
@login_required
def execute_command_endpoint(sandbox_id: int):
    """
    Executes a controlled command inside the sandbox.
    Supports asynchronous execution (default) or synchronous execution.
    """
    user = get_current_user(db_path=get_db_path())
    sandbox, err, status = verify_sandbox_ownership(sandbox_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    data = request.get_json(silent=True) or {}
    command = data.get("command")
    is_async = data.get("async", True)
    enable_monitoring = data.get("enable_monitoring", True)
    timeout = data.get("timeout")
    print("\n========== EXECUTION DEBUG ==========")
    print("Sandbox ID:", sandbox_id)
    print("Command:", repr(command))
    print("Async:", repr(is_async))
    print("Monitoring:", repr(enable_monitoring))
    print("Timeout:", repr(timeout))
    print("=====================================\n")

    if not command:
        return json_error("Command field is required.", "INVALID_INPUT", 400)

    db_path = get_db_path()

    try:
        if is_async:
            run_id, proc = spawn_process(
                sandbox_id=sandbox_id,
                command=command,
                working_dir=sandbox["working_dir"],
                enable_monitoring=enable_monitoring,
                db_path=db_path
            )
            print("[LIFECYCLE] Immediately after spawn:", proc.poll(), flush=True)

            import time
            time.sleep(3)

            print("[LIFECYCLE] After 3 seconds:", proc.poll(), flush=True)
            print(
            f"[SPAWN DEBUG] run={run_id}, pid={proc.pid}, "
            f"poll={proc.poll()}, alive={proc.poll() is None}",
            flush=True
            )
            return json_success(
                data={
                    "run_id": run_id,
                    "pid": proc.pid,
                    "status": "RUNNING",
                    "sandbox_id": sandbox_id,
                },
                message="Process spawned successfully in background.",
                status_code=201
            )
        else:
            # Synchronous execution
            run_record = execute_sync(
                sandbox_id=sandbox_id,
                command=command,
                working_dir=sandbox["working_dir"],
                timeout=float(timeout) if timeout else None,
                enable_monitoring=enable_monitoring,
                db_path=db_path
            )
            return json_success(data=run_record, message="Execution completed.")

    except ValueError as e:
        return json_error(str(e), "INVALID_COMMAND_OR_PATH", 400)
    except Exception as e:
        return json_error(f"Execution failed: {str(e)}", "SERVER_ERROR", 500)


@api_bp.route("/executions/<int:run_id>", methods=["GET"])
@login_required
def get_execution_endpoint(run_id: int):
    """Retrieves execution details, PID, status, and output streams."""
    user = get_current_user(db_path=get_db_path())
    db_path = get_db_path()
    run_record, err, status = verify_execution_ownership(run_id, user, db_path=db_path)
    if err:
        return json_error(err["message"], err["code"], status)

    # Check if active process completed naturally in background
    proc = registry.get_process(run_id)

    print(
    f"[POLL DEBUG] run={run_id}, "
    f"proc_exists={proc is not None}, "
    f"poll={proc.poll() if proc else 'NO PROCESS'}, "
    f"db_status={run_record['status']}",
    flush=True
    )

    if proc and proc.poll() is not None and run_record["status"] == "RUNNING":
        out, err_stream = proc.communicate()
        exit_code = proc.returncode
        status_str = "COMPLETED" if exit_code == 0 else "FAILED"

        monitor = registry.get_monitor(run_id)
        if monitor is not None:
            monitor.stop(timeout=2.0)

        end_iso = datetime.now(timezone.utc).isoformat()

        update_execution_run(
            run_id=run_id,
            status=status_str,
            exit_code=exit_code,
            stdout=out or "",
            stderr=err_stream or "",
            end_time=end_iso,
            db_path=db_path
        )

        registry.unregister(run_id)
        run_record = get_execution_run_by_id(run_id, db_path=db_path)

    return json_success(data=run_record)


@api_bp.route("/executions/<int:run_id>/stop", methods=["POST"])
@login_required
def stop_execution_endpoint(run_id: int):
    """Stops an active execution run using SIGTERM -> SIGKILL."""
    user = get_current_user(db_path=get_db_path())
    db_path = get_db_path()
    run_record, err, status = verify_execution_ownership(run_id, user, db_path=db_path)
    if err:
        return json_error(err["message"], err["code"], status)

    if run_record["status"] not in ("RUNNING", "QUEUED"):
        return json_error(
            f"Cannot stop process with status '{run_record['status']}'.",
            "INVALID_STATE",
            400
        )

    data = request.get_json(silent=True) or {}
    grace_period = float(data.get("grace_period", 2.0))

    stopped = stop_execution(run_id=run_id, grace_period=grace_period, db_path=db_path)
    updated_run = get_execution_run_by_id(run_id, db_path=db_path)

    return json_success(
        data=updated_run,
        message="Process stop sequence completed." if stopped else "Process was already stopped."
    )


@api_bp.route("/sandboxes/<int:sandbox_id>/executions", methods=["GET"])
@login_required
def list_sandbox_executions_endpoint(sandbox_id: int):
    """Lists execution history for a given sandbox."""
    user = get_current_user(db_path=get_db_path())
    sandbox, err, status = verify_sandbox_ownership(sandbox_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    limit = int(request.args.get("limit", 50))
    runs = list_execution_runs_for_sandbox(sandbox_id, limit=limit, db_path=get_db_path())
    return json_success(data=runs)


@api_bp.route("/executions/<int:run_id>/metrics", methods=["GET"])
@login_required
def get_execution_metrics_endpoint(run_id: int):
    """Returns telemetry time-series metrics recorded during process execution."""
    user = get_current_user(db_path=get_db_path())
    run_record, err, status = verify_execution_ownership(run_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    limit = int(request.args.get("limit", 100))
    metrics = get_metrics_for_run(run_id=run_id, limit=limit, db_path=get_db_path())
    return json_success(data=metrics)


@api_bp.route("/executions/<int:run_id>/analytics", methods=["GET"])
@login_required
def execution_analytics_endpoint(run_id: int):
    """Calculates statistical resource averages and peaks for a specific run."""
    user = get_current_user(db_path=get_db_path())
    run_record, err, status = verify_execution_ownership(run_id, user, db_path=get_db_path())
    if err:
        return json_error(err["message"], err["code"], status)

    analytics = get_run_resource_analytics(run_id=run_id, db_path=get_db_path())
    return json_success(data=analytics)


# ==========================================
# 4. MONITORING, DASHBOARD & AUDIT LOGS
# ==========================================

@api_bp.route("/system/stats", methods=["GET"])
@login_required
def system_stats_endpoint():
    """Returns host system health and utilization (WSL2 environment)."""
    stats = get_host_system_stats()
    return json_success(data=stats)


@api_bp.route("/dashboard/summary", methods=["GET"])
@login_required
def dashboard_summary_endpoint():
    """Returns aggregated summary metrics for the authenticated user's dashboard."""
    user = get_current_user(db_path=get_db_path())
    summary = get_user_dashboard_summary(user_id=user["id"], db_path=get_db_path())
    return json_success(data=summary)


@api_bp.route("/activity", methods=["GET"])
@login_required
def activity_logs_endpoint():
    """Returns audit trail logs for the current user (admins can query ?all=true)."""
    user = get_current_user(db_path=get_db_path())
    limit = int(request.args.get("limit", 20))

    user_filter = None if (user["role"] == "admin" and request.args.get("all") == "true") else user["id"]
    logs = list_recent_activity(user_id=user_filter, limit=limit, db_path=get_db_path())
    return json_success(data=logs)


# ==========================================
# 5. LAB INTEGRATION ENDPOINTS
# ==========================================

from threading import Thread
from app.os_lab.scheduling import fcfs, sjf, round_robin, validate_processes
from app.os_lab.memory import allocate_memory
from app.os_lab.deadlock import bankers_algorithm
from app.os_lab.synchronization import BoundedBuffer
from app.os_lab.ipc import pipe_communication
from app.os_lab.process_control import run_process_demonstration, demonstrate_process_timeout
from app.os_lab.filesystem_isolation import demonstrate_filesystem_isolation, verify_path_boundaries
from app.os_lab.signals_telemetry import demonstrate_signal_termination, demonstrate_resource_telemetry
from app.dbms_lab.demonstrations import execute_dbms_demonstration


@api_bp.route("/labs/os/run", methods=["POST"])
@login_required
def run_os_lab_endpoint():
    """
    Executes an OS Lab demonstration.
    Algorithmic modules (scheduling, memory, deadlock, sync) run as manager-policy simulations.
    System modules (ipc, process_control, isolation, signals) run through Bubblewrap sandbox execution.
    Logs execution to activity_logs and execution_runs.
    """
    user = get_current_user(db_path=get_db_path())
    data = request.get_json(silent=True) or {}
    module = str(data.get("module", "")).strip().lower()
    payload = data.get("payload", {})
    if isinstance(payload, str):
        import json
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    db_path = get_db_path()

    # Resolve active sandbox workspace for the user
    user_sandbox = get_or_create_default_sandbox(user["id"], db_path=db_path)
    sandbox_id = int(data.get("sandbox_id") or user_sandbox.get("id"))
    working_dir = user_sandbox.get("working_dir")

    try:
        if module == "scheduling":
            processes = payload.get("processes", [])
            validate_processes(processes)
            algo = payload.get("algorithm", "fcfs")
            quantum = int(payload.get("quantum", 2))
            if algo == "fcfs":
                result = fcfs(processes)
            elif algo == "sjf":
                result = sjf(processes)
            elif algo == "round_robin":
                result = round_robin(processes, quantum)
            else:
                return json_error("Unknown scheduling algorithm.", "INVALID_INPUT", 400)

            log_activity("OS_LAB_SCHEDULING", user_id=user["id"], details=f"Algorithm {algo} on {len(processes)} processes", db_path=db_path)
            return json_success(data=result, message=f"CPU scheduling ({algo}) calculated successfully.")

        elif module == "memory":
            blocks = payload.get("blocks", [100, 500, 200, 300, 600])
            processes = payload.get("processes", [212, 417, 112, 426])
            strategy = payload.get("strategy", "first_fit")
            result = allocate_memory(blocks, processes, strategy)
            log_activity("OS_LAB_MEMORY", user_id=user["id"], details=f"Memory allocation ({strategy}) for {len(processes)} processes", db_path=db_path)
            return json_success(data=result, message=f"Memory allocation ({strategy}) completed.")

        elif module == "deadlock":
            available = payload.get("available", [3, 3, 2])
            allocation = payload.get("allocation", [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]])
            maximum = payload.get("maximum", [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]])
            result = bankers_algorithm(available, allocation, maximum)
            log_activity("OS_LAB_DEADLOCK", user_id=user["id"], details=f"Banker's Algorithm safe={result.get('safe')}", db_path=db_path)
            return json_success(data=result, message="Banker's algorithm evaluated successfully.")

        elif module == "synchronization":
            capacity = int(payload.get("capacity", 3))
            items = payload.get("items", [1, 2, 3, 4, 5])
            buffer = BoundedBuffer(capacity)
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
            log_activity("OS_LAB_SYNCHRONIZATION", user_id=user["id"], details=f"Bounded buffer capacity {capacity}, {len(items)} items", db_path=db_path)
            return json_success(data=result, message="Producer-consumer synchronization demonstration completed.")

        elif module == "ipc":
            message = str(payload.get("message", "Hello from Parent Process!"))
            result = pipe_communication(message, sandbox_id=sandbox_id, working_dir=working_dir, db_path=db_path)
            log_activity("OS_LAB_IPC", user_id=user["id"], details=f"IPC pipe demonstration: {message[:40]}", db_path=db_path)
            return json_success(data=result, message="IPC pipe demonstration executed in Bubblewrap sandbox.")

        elif module in ("process_control", "lifecycle"):
            command = payload.get("command", [sys.executable, "-c", "import os; print(f'Process Lifecycle OK, PID: {os.getpid()}')"])
            timeout = float(payload.get("timeout", 5.0))
            result = run_process_demonstration(sandbox_id=sandbox_id, command=command, working_dir=working_dir, timeout=timeout, db_path=db_path)
            return json_success(data=result, message="Process lifecycle demonstration executed in sandbox.")

        elif module == "isolation":
            result = demonstrate_filesystem_isolation(sandbox_id=sandbox_id, working_dir=working_dir, db_path=db_path)
            return json_success(data=result, message="Bubblewrap filesystem isolation probe executed successfully.")

        elif module in ("signals", "telemetry"):
            if payload.get("action") == "telemetry":
                result = demonstrate_resource_telemetry(sandbox_id=sandbox_id, working_dir=working_dir, db_path=db_path)
            else:
                result = demonstrate_signal_termination(sandbox_id=sandbox_id, working_dir=working_dir, db_path=db_path)
            return json_success(data=result, message="OS signals and telemetry demonstration completed.")

        else:
            return json_error(f"Unknown OS Lab module: '{module}'.", "INVALID_INPUT", 400)

    except ValueError as e:
        return json_error(str(e), "INVALID_INPUT", 400)
    except Exception as e:
        return json_error(f"OS Lab execution failed: {str(e)}", "SERVER_ERROR", 500)


@api_bp.route("/labs/dbms/run", methods=["POST"])
@login_required
def run_dbms_lab_endpoint():
    """
    Executes a DBMS Lab demonstration against the persistent project SQLite database.
    Demonstrates 8 core DBMS concepts with automatic cleanup and transaction safety.
    """
    user = get_current_user(db_path=get_db_path())
    data = request.get_json(silent=True) or {}
    module = str(data.get("module", "")).strip().lower()

    if not module:
        return json_error("DBMS module parameter is required.", "INVALID_INPUT", 400)

    db_path = get_db_path()

    try:
        result = execute_dbms_demonstration(module, db_path=db_path)
        log_activity(
            action=f"DBMS_LAB_{module.upper()}",
            user_id=user["id"],
            details=f"Demonstration: {module} against persistent SQLite database",
            db_path=db_path,
        )
        return json_success(
            data={"module": module, "result": result},
            message=f"DBMS demonstration '{module}' executed successfully.",
        )
    except ValueError as e:
        return json_error(str(e), "INVALID_INPUT", 400)
    except Exception as e:
        return json_error(f"DBMS execution failed: {str(e)}", "SERVER_ERROR", 500)
