"""
Process Signals & Resource Telemetry for OS Lab.
Demonstrates operating system process signaling and telemetry by reusing:
- spawn_process and stop_execution (SIGTERM graceful termination & SIGKILL escalation)
- ProcessMonitorThread and sample_process_metrics (psutil CPU and memory accounting)
- get_host_system_stats (Host CPU, RAM, and Disk metrics)
"""

import os
import sys
import time
from typing import Any, Dict, Optional

import psutil

from app.database import (
    get_execution_run_by_id,
    get_metrics_for_run,
    get_run_resource_analytics,
)
from app.monitor import get_host_system_stats, sample_process_metrics
from app.sandbox import (
    ensure_sandbox_dir,
    spawn_process,
    stop_execution,
    terminate_process,
)


def demonstrate_signal_termination(
    sandbox_id: int,
    working_dir: str,
    grace_period: float = 1.0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Demonstrates OS signal termination sequence (SIGTERM -> SIGKILL):
    1. Spawns an isolated background process that runs a sleep workload.
    2. Samples its PID and verify it is running in the OS.
    3. Issues stop_execution() which sends SIGTERM and escalates to SIGKILL if needed.
    4. Confirms process termination and status update to TERMINATED in database.
    """
    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    run_id, proc = spawn_process(
        sandbox_id=sandbox_id,
        command=cmd,
        working_dir=working_dir,
        enable_monitoring=True,
        db_path=db_path,
    )
    pid = proc.pid
    initial_alive = psutil.pid_exists(pid)
    initial_metrics = sample_process_metrics(pid)

    # Allow brief window for monitor to capture at least one sample
    time.sleep(0.3)

    # Terminate via signal sequence
    stopped = stop_execution(run_id=run_id, grace_period=grace_period, db_path=db_path)
    time.sleep(0.1)

    still_alive = psutil.pid_exists(pid)
    final_record = get_execution_run_by_id(run_id, db_path=db_path) or {}

    return {
        "sandbox_id": sandbox_id,
        "run_id": run_id,
        "pid": pid,
        "signals_tested": [
            {"signal": "SIGTERM (15)", "purpose": "Graceful termination request"},
            {"signal": "SIGKILL (9)", "purpose": "Forceful termination escalation (if needed)"},
        ],
        "initial_state": {
            "pid_exists": initial_alive,
            "metrics": initial_metrics,
        },
        "termination_result": {
            "stopped_successfully": stopped,
            "pid_still_exists": still_alive,
            "db_status": final_record.get("status"),
            "exit_code": final_record.get("exit_code"),
            "end_time": final_record.get("end_time"),
        },
    }


def demonstrate_resource_telemetry(
    sandbox_id: int,
    working_dir: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Demonstrates operating system process accounting and resource telemetry:
    1. Runs a CPU/memory workload while ProcessMonitorThread records metrics.
    2. Collects time-series samples (CPU %, RSS bytes, thread count).
    3. Computes aggregate analytics (peak CPU %, average RSS).
    """
    workload = (
        "import time\n"
        "data = [bytearray(1024 * 1024) for _ in range(5)]\n"
        "for _ in range(5):\n"
        "    sum(i * i for i in range(100000))\n"
        "    time.sleep(0.08)\n"
    )

    run_id, proc = spawn_process(
        sandbox_id=sandbox_id,
        command=[sys.executable, "-c", workload],
        working_dir=working_dir,
        enable_monitoring=True,
        db_path=db_path,
    )

    try:
        proc.wait(timeout=5.0)
    except Exception:
        stop_execution(run_id, grace_period=0.2, db_path=db_path)

    time.sleep(0.3)
    stop_execution(run_id=run_id, db_path=db_path)

    metrics = get_metrics_for_run(run_id, limit=20, db_path=db_path)
    analytics = get_run_resource_analytics(run_id, db_path=db_path)
    host_stats = get_host_system_stats()

    return {
        "run_id": run_id,
        "pid": proc.pid,
        "sample_count": len(metrics),
        "samples": metrics[:5],
        "analytics": analytics,
        "host_system_stats": host_stats,
    }

