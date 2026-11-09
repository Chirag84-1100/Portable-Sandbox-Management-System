"""Inter-Process Communication using operating system pipes."""

import subprocess
import sys


def pipe_communication(message: str) -> dict:
    """
    Demonstrates Inter-Process Communication using operating system pipes.
    Replaces unsafe in-process os.fork() with an isolated subprocess connected
    via standard operating system pipes (stdin and stdout).
    """
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
