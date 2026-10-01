"""
OS Process Engine & Sandbox Supervisor for Portable Sandbox Management System.
Demonstrates Operating Systems concepts:
- Process lifecycle management (QUEUED, RUNNING, COMPLETED, FAILED, TERMINATED, TIMED_OUT)
- Process spawning and execution bounded to sandbox working directories
- Path traversal validation and security boundary enforcement
- Process group isolation (start_new_session) and signal dispatching
- Two-stage termination protocol: graceful SIGTERM followed by forceful SIGKILL
- Stream capture (stdout/stderr) and PID tracking
- Integration with DBMS layer for audit and execution logging

Academic Note:
This engine implements user-space process supervision, controlled execution, and resource
telemetry. It does not provide hypervisor-level virtualization or complete kernel namespace isolation.
"""

import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.database import (
    create_execution_run,
    get_execution_run_by_id,
    log_activity,
    update_execution_run,
)

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOXES_ROOT = (BASE_DIR / "sandboxes").resolve()


# ==========================================
# 1. PATH VALIDATION & DIRECTORY ISOLATION
# ==========================================

def validate_sandbox_path(working_dir: Union[str, Path]) -> Path:
    """
    Validates that a working directory is strictly inside the project sandboxes root.
    Rejects directory traversal (e.g., '../', escaping symlinks, or absolute paths outside sandboxes).
    Rejects targeting the sandboxes root folder itself (processes must execute in a subfolder).
    """
    raw_path = Path(working_dir)
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    else:
        resolved = (SANDBOXES_ROOT / raw_path).resolve()

    try:
        is_sub = resolved.is_relative_to(SANDBOXES_ROOT)
    except AttributeError:
        # Python < 3.9 compatibility fallback
        common = os.path.commonpath([str(resolved), str(SANDBOXES_ROOT)])
        is_sub = common == str(SANDBOXES_ROOT)

    if not is_sub or resolved == SANDBOXES_ROOT:
        raise ValueError(
            f"Path validation failed: '{working_dir}' escapes or targets the sandbox root boundary."
        )

    return resolved


def ensure_sandbox_dir(working_dir: Union[str, Path]) -> Path:
    """
    Validates and creates the target sandbox directory if it does not already exist.
    Returns the resolved Path object.
    """
    resolved = validate_sandbox_path(working_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


# ==========================================
# 2. COMMAND SANITIZATION & PARSING
# ==========================================

def sanitize_command(command: Union[str, List[str]]) -> List[str]:
    """
    Converts command input into a tokenized argument list using shlex.split without shell interpretation.
    Guarantees shell=False execution, preventing arbitrary shell operator injection (; && | ` $).
    """
    if isinstance(command, str):
        tokens = shlex.split(command)
    elif isinstance(command, (list, tuple)):
        tokens = [str(t) for t in command]
    else:
        raise ValueError("Command must be a string or a list of arguments.")

    if not tokens or not tokens[0].strip():
        raise ValueError("Command cannot be empty.")

    return tokens


# ==========================================
# 3. ACTIVE PROCESS REGISTRY
# ==========================================

class ProcessRegistry:
    """Thread-safe registry tracking active supervised processes in memory."""

    def __init__(self):
        self._lock = threading.Lock()
        self._processes: Dict[int, subprocess.Popen] = {}
        self._monitors: Dict[int, Any] = {}

    def register(self, run_id: int, proc: subprocess.Popen, monitor: Optional[Any] = None) -> None:
        with self._lock:
            self._processes[run_id] = proc
            if monitor is not None:
                self._monitors[run_id] = monitor

    def unregister(self, run_id: int) -> Tuple[Optional[subprocess.Popen], Optional[Any]]:
        with self._lock:
            proc = self._processes.pop(run_id, None)
            monitor = self._monitors.pop(run_id, None)
            return proc, monitor

    def get_process(self, run_id: int) -> Optional[subprocess.Popen]:
        with self._lock:
            return self._processes.get(run_id)

    def get_monitor(self, run_id: int) -> Optional[Any]:
        with self._lock:
            return self._monitors.get(run_id)

    def list_active(self) -> Dict[int, int]:
        """Returns dict of {run_id: pid} for currently active processes."""
        with self._lock:
            return {
                run_id: p.pid
                for run_id, p in list(self._processes.items())
                if p.poll() is None
            }


registry = ProcessRegistry()


# ==========================================
# 4. PROCESS TERMINATION PROTOCOL (SIGTERM -> SIGKILL)
# ==========================================

def terminate_process(
    pid: int,
    proc: Optional[subprocess.Popen] = None,
    grace_period: float = 2.0
) -> bool:
    """
    Terminates an OS process using a robust two-stage protocol:
    1. Dispatches SIGTERM to the process group (allowing graceful shutdown).
    2. Waits up to grace_period seconds for termination.
    3. Escalates to SIGKILL if the process fails to exit.
    Reaps the process to prevent zombie states.
    """
    # Check if process is still alive
    if proc is not None:
        if proc.poll() is not None:
            return True
    else:
        try:
            os.kill(pid, 0)
        except OSError:
            return True

    # Obtain Process Group ID if available
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        pgid = None

    # Step 1: Send SIGTERM to process group or PID
    try:
        if pgid is not None and pgid == pid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return True

    # Step 2: Poll for exit within grace period
    deadline = time.time() + max(0.1, grace_period)
    while time.time() < deadline:
        if proc is not None:
            if proc.poll() is not None:
                return True
        else:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
        time.sleep(0.05)

    # Step 3: Escalate to SIGKILL if still alive
    try:
        if pgid is not None and pgid == pid:
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    # Final reap / wait
    if proc is not None:
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass

    try:
        os.kill(pid, 0)
        return False
    except OSError:
        return True


# ==========================================
# 5. EXECUTION & PROCESS LIFECYCLE SUPERVISOR
# ==========================================

def spawn_process(
    sandbox_id: int,
    command: Union[str, List[str]],
    working_dir: Union[str, Path],
    run_id: Optional[int] = None,
    enable_monitoring: bool = False,
    db_path: Optional[str] = None,
) -> Tuple[int, subprocess.Popen]:
    """
    Spawns a controlled process inside the designated sandbox working directory.
    - Tokenizes command (shell=False)
    - Starts process in a new session (process group)
    - Captures stdout/stderr via pipes
    - Records PID and RUNNING state in SQLite database
    - Optionally starts background resource monitoring thread
    Returns (run_id, Popen object).
    """
    tokens = sanitize_command(command)
    cmd_str = " ".join(tokens)
    target_dir = ensure_sandbox_dir(working_dir)

    # If run_id not provided, record in execution_runs
    if run_id is None:
        run_id = create_execution_run(
            sandbox_id=sandbox_id,
            command=cmd_str,
            status="QUEUED",
            db_path=db_path
        )

    # Clean execution environment
    clean_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(target_dir),
        "PYTHONUNBUFFERED": "1",
    }

    # Spawn process in new process group
    proc = subprocess.Popen(
        tokens,
        cwd=str(target_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=clean_env,
        start_new_session=True,  # New session/process group for clean signal handling
    )

    start_iso = datetime.now(timezone.utc).isoformat()
    update_execution_run(
        run_id=run_id,
        status="RUNNING",
        pid=proc.pid,
        start_time=start_iso,
        db_path=db_path
    )

    monitor_thread = None
    if enable_monitoring:
        # Import lazily to avoid circular dependencies
        from app.monitor import ProcessMonitorThread
        monitor_thread = ProcessMonitorThread(
            pid=proc.pid,
            run_id=run_id,
            interval=0.15,
            db_path=db_path
        )
        monitor_thread.start()

    registry.register(run_id, proc, monitor_thread)
    log_activity(
        action="PROCESS_SPAWN",
        details=f"Spawned PID {proc.pid} for run {run_id} in {target_dir.name}",
        db_path=db_path
    )

    return run_id, proc


def stop_execution(
    run_id: int,
    grace_period: float = 2.0,
    db_path: Optional[str] = None
) -> bool:
    """
    Terminates an active execution run using the two-stage SIGTERM -> SIGKILL protocol.
    Updates the database with TERMINATED state, output streams, and exit code.
    """
    proc = registry.get_process(run_id)
    monitor = registry.get_monitor(run_id)

    # Stop monitor if running
    if monitor is not None and hasattr(monitor, "stop"):
        monitor.stop()

    pid = proc.pid if proc else None
    if pid is None:
        # Check database for PID
        record = get_execution_run_by_id(run_id, db_path=db_path)
        if record and record.get("pid"):
            pid = record["pid"]

    if pid is None:
        return False

    # Execute termination protocol
    success = terminate_process(pid=pid, proc=proc, grace_period=grace_period)

    # Capture remaining output if proc object is available
    stdout_text = ""
    stderr_text = ""
    exit_code = -signal.SIGTERM
    if proc is not None:
        try:
            out, err = proc.communicate(timeout=1.0)
            stdout_text = out or ""
            stderr_text = err or ""
            if proc.returncode is not None:
                exit_code = proc.returncode
        except Exception:
            pass

    end_iso = datetime.now(timezone.utc).isoformat()
    update_execution_run(
        run_id=run_id,
        status="TERMINATED",
        exit_code=exit_code,
        stdout=stdout_text,
        stderr=stderr_text,
        end_time=end_iso,
        db_path=db_path
    )

    registry.unregister(run_id)
    log_activity(
        action="PROCESS_TERMINATE",
        details=f"Terminated run {run_id} (PID {pid}) with status code {exit_code}",
        db_path=db_path
    )

    return success


def execute_sync(
    sandbox_id: int,
    command: Union[str, List[str]],
    working_dir: Union[str, Path],
    timeout: Optional[float] = None,
    enable_monitoring: bool = False,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a controlled command synchronously with optional timeout.
    Monitors execution lifecycle and records exit state (COMPLETED, FAILED, or TIMED_OUT).
    Returns the updated execution run dictionary.
    """
    run_id, proc = spawn_process(
        sandbox_id=sandbox_id,
        command=command,
        working_dir=working_dir,
        enable_monitoring=enable_monitoring,
        db_path=db_path
    )

    status = "COMPLETED"
    stdout_text = ""
    stderr_text = ""
    exit_code = 0

    try:
        stdout_text, stderr_text = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
        status = "COMPLETED" if exit_code == 0 else "FAILED"
    except subprocess.TimeoutExpired:
        status = "TIMED_OUT"
        terminate_process(pid=proc.pid, proc=proc, grace_period=0.5)
        try:
            out, err = proc.communicate(timeout=0.5)
            stdout_text = out or ""
            stderr_text = (err or "") + f"\n[Process killed: timed out after {timeout}s]"
        except Exception:
            stderr_text = f"[Process killed: timed out after {timeout}s]"
        exit_code = -signal.SIGKILL

    # Stop monitor if running
    monitor = registry.get_monitor(run_id)
    if monitor and hasattr(monitor, "stop"):
        monitor.stop()

    registry.unregister(run_id)

    end_iso = datetime.now(timezone.utc).isoformat()
    update_execution_run(
        run_id=run_id,
        status=status,
        exit_code=exit_code,
        stdout=stdout_text or "",
        stderr=stderr_text or "",
        end_time=end_iso,
        db_path=db_path
    )

    return get_execution_run_by_id(run_id, db_path=db_path) or {}
