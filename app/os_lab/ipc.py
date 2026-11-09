"""Inter-Process Communication using operating system pipes."""

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union


def pipe_communication(
    message: str,
    sandbox_id: Optional[int] = None,
    working_dir: Optional[Union[str, Path]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Demonstrates Inter-Process Communication using operating system pipes.
    - If sandbox_id and working_dir are provided: executes inside Bubblewrap via
      execute_sync(), ensuring true IPC namespace isolation (CLONE_NEWIPC) and
      recording the execution in the execution_runs table.
    - Otherwise: executes via an isolated subprocess connected via OS pipes
      (stdin/stdout), replacing unsafe in-process os.fork().
    """
    if sandbox_id is not None and working_dir is not None:
        from app.sandbox import execute_sync

        # Execute inside the Bubblewrap namespace container
        pipe_probe_script = (
            "import os, sys\n"
            "read_fd, write_fd = os.pipe()\n"
            f"msg = {repr(str(message))}\n"
            "os.write(write_fd, msg.encode('utf-8'))\n"
            "os.close(write_fd)\n"
            "received = os.read(read_fd, 4096).decode('utf-8')\n"
            "os.close(read_fd)\n"
            "sys.stdout.write(f'Child received: {received}')\n"
            "sys.stdout.flush()\n"
        )

        run_record = execute_sync(
            sandbox_id=sandbox_id,
            command=[sys.executable, "-c", pipe_probe_script],
            working_dir=working_dir,
            timeout=5.0,
            enable_monitoring=False,
            db_path=db_path,
        )

        stdout_text = run_record.get("stdout", "").strip()

        return {
            "message_sent": str(message),
            "child_pid": run_record.get("pid"),
            "child_response": stdout_text,
            "communication": "Successful" if run_record.get("status") == "COMPLETED" else "Failed",
            "method": "OS pipe",
            "run_id": run_record.get("id"),
            "sandbox_id": sandbox_id,
            "isolation": "Bubblewrap IPC Namespace (CLONE_NEWIPC)",
        }

    # Subprocess pipe fallback (standalone/testing)
    child_script = (
        "import sys\n"
        "received = sys.stdin.read()\n"
        "sys.stdout.write(f'Child received: {received}')\n"
        "sys.stdout.flush()\n"
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_data, stderr_data = proc.communicate(input=str(message), timeout=5.0)

    if proc.returncode != 0:
        raise RuntimeError(
            f"IPC process error (exit code {proc.returncode}): {stderr_data.strip()}"
        )

    return {
        "message_sent": str(message),
        "child_pid": proc.pid,
        "child_response": stdout_data.strip(),
        "communication": "Successful",
        "method": "OS pipe",
    }
