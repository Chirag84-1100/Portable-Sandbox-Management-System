"""
Process Management & Lifecycle Control for OS Lab.
Demonstrates operating system process management concepts by reusing the existing
sandbox execution engine (app.sandbox):
- Process creation and execution tracking
- State transitions (QUEUED -> RUNNING -> COMPLETED / FAILED / TIMED_OUT)
- PID management, exit code capture, and stream redirection
- Process timeout enforcement
"""

import sys
from typing import Any, Dict, List, Optional, Union

from app.sandbox import (
    ensure_sandbox_dir,
    execute_sync,
    sanitize_command,
    spawn_process,
    stop_execution,
)


def run_process_demonstration(
    sandbox_id: int,
    command: Union[str, List[str]],
    working_dir: str,
    timeout: Optional[float] = 10.0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes a process synchronously inside the specified sandbox workspace,
    tracking full lifecycle metadata including PID, exit code, and outputs.
    """
    sanitized = sanitize_command(command)
    run_record = execute_sync(
        sandbox_id=sandbox_id,
        command=sanitized,
        working_dir=working_dir,
        timeout=timeout,
        enable_monitoring=False,
        db_path=db_path,
    )

    return {
        "sandbox_id": sandbox_id,
        "command": " ".join(sanitized),
        "run_id": run_record.get("id"),
        "pid": run_record.get("pid"),
        "status": run_record.get("status"),
        "exit_code": run_record.get("exit_code"),
        "stdout": run_record.get("stdout", "").strip(),
        "stderr": run_record.get("stderr", "").strip(),
        "start_time": run_record.get("start_time"),
        "end_time": run_record.get("end_time"),
        "lifecycle_stages": ["QUEUED", "RUNNING", run_record.get("status", "COMPLETED")],
    }


def demonstrate_process_timeout(
    sandbox_id: int,
    working_dir: str,
    sleep_seconds: float = 5.0,
    timeout: float = 1.0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Demonstrates OS process timeout enforcement: spawns a process that sleeps
    longer than the allocated quantum/timeout and verifies automatic termination.
    """
    cmd = [
        sys.executable,
        "-c",
        f"import time; time.sleep({sleep_seconds})",
    ]
    return run_process_demonstration(
        sandbox_id=sandbox_id,
        command=cmd,
        working_dir=working_dir,
        timeout=timeout,
        db_path=db_path,
    )

