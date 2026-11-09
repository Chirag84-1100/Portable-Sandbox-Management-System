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

BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOXES_ROOT = Path(
    os.environ.get("SANDBOX_DATA_ROOT", str(BASE_DIR))
).expanduser().resolve() / "sandboxes"


def validate_sandbox_path(working_dir: Union[str, Path]) -> Path:
    raw_path = Path(working_dir)
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    else:
        resolved = (SANDBOXES_ROOT / raw_path).resolve()

    try:
        is_sub = resolved.is_relative_to(SANDBOXES_ROOT)
    except AttributeError:
        
        common = os.path.commonpath([str(resolved), str(SANDBOXES_ROOT)])
        is_sub = common == str(SANDBOXES_ROOT)

    if not is_sub or resolved == SANDBOXES_ROOT:
        raise ValueError(
            f"Path validation failed: '{working_dir}' escapes or targets the sandbox root boundary."
        )

    return resolved


def ensure_sandbox_dir(working_dir: Union[str, Path]) -> Path:
    resolved = validate_sandbox_path(working_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved

def sanitize_command(command: Union[str, List[str]]) -> List[str]:

    if isinstance(command, str):
        tokens = shlex.split(command)
    elif isinstance(command, (list, tuple)):
        tokens = [str(t) for t in command]
    else:
        raise ValueError("Command must be a string or a list of arguments.")

    if not tokens or not tokens[0].strip():
        raise ValueError("Command cannot be empty.")

    return tokens


class ProcessRegistry:
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

def terminate_process(
    pid: int,
    proc: Optional[subprocess.Popen] = None,
    grace_period: float = 2.0
) -> bool:
   
    if proc is not None:
        if proc.poll() is not None:
            return True
    else:
        try:
            os.kill(pid, 0)
        except OSError:
            return True

    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        pgid = None

    try:
        if pgid is not None and pgid == pid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return True
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

    try:
        if pgid is not None and pgid == pid:
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass

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


def build_isolated_command(
    tokens: List[str],
    target_dir: Path,
) -> List[str]:
    """Build a fail-closed Bubblewrap command for Linux execution."""
    import shutil

    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError(
            "Isolation unavailable: bubblewrap (bwrap) is not installed."
        )

    target_dir = target_dir.resolve()
    if not target_dir.is_dir():
        raise ValueError("Sandbox workspace must be an existing directory.")

    return [
        bwrap,
        "--new-session",
        "--unshare-all",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--bind", str(target_dir), str(target_dir),
        "--chdir", str(target_dir),
        "--",
        *tokens,
    ]


def spawn_process(
    sandbox_id: int,
    command: Union[str, List[str]],
    working_dir: Union[str, Path],
    run_id: Optional[int] = None,
    enable_monitoring: bool = False,
    db_path: Optional[str] = None,
) -> Tuple[int, subprocess.Popen]:
    
    tokens = sanitize_command(command)
    cmd_str = " ".join(tokens)
    target_dir = ensure_sandbox_dir(working_dir)

    if run_id is None:
        run_id = create_execution_run(
            sandbox_id=sandbox_id,
            command=cmd_str,
            status="QUEUED",
            db_path=db_path
        )

    clean_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(target_dir),
        "PYTHONUNBUFFERED": "1",
    }

    isolated_tokens = build_isolated_command(tokens, target_dir)

    proc = subprocess.Popen(
        isolated_tokens,
        cwd=str(target_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=clean_env,
        start_new_session=True,  
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

    proc = registry.get_process(run_id)
    monitor = registry.get_monitor(run_id)
    if monitor is not None and hasattr(monitor, "stop"):
        monitor.stop()

    pid = proc.pid if proc else None
    if pid is None:
        record = get_execution_run_by_id(run_id, db_path=db_path)
        if record and record.get("pid"):
            pid = record["pid"]

    if pid is None:
        return False

    success = terminate_process(pid=pid, proc=proc, grace_period=grace_period)

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
