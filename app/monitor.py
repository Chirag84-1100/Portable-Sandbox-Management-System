
"""
Resource Monitoring Component for Portable Sandbox Management System.

Tracks CPU utilization, RSS/VMS memory, and thread count using psutil.
Resource samples are periodically persisted through the database layer.
"""

import threading
import time
from typing import Any, Dict, Optional

import psutil

from app.database import log_resource_metric


class ProcessMonitorThread(threading.Thread):
    """Periodically collect and persist process resource metrics."""

    def __init__(
        self,
        pid: int,
        run_id: int,
        interval: float = 0.5,
        db_path: Optional[str] = None,
        max_samples: int = 1000,
    ):
        super().__init__(name=f"Monitor-PID-{pid}", daemon=True)

        self.pid = pid
        self.run_id = run_id
        self.interval = max(0.1, float(interval))
        self.db_path = db_path
        self.max_samples = max_samples
        self._stop_event = threading.Event()
        self.sample_count = 0

    def run(self) -> None:
        """Sample CPU over a real interval, then persist resource metrics."""
        try:
            proc = psutil.Process(self.pid)

            # Prime CPU counters before measuring the first interval.
            proc.cpu_percent(interval=None)

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            return

        while (
            not self._stop_event.is_set()
            and self.sample_count < self.max_samples
        ):
            # Wait without blocking shutdown for the full interval.
            if self._stop_event.wait(self.interval):
                break

            try:
                if not proc.is_running():
                    break

                if proc.status() == psutil.STATUS_ZOMBIE:
                    break

                # Non-blocking CPU measurement uses time since the last
                # CPU sample. The preceding wait provides the sample interval.
                cpu = proc.cpu_percent(interval=None)

                # Read memory and thread metrics independently.
                mem = proc.memory_info()
                threads = proc.num_threads()

                log_resource_metric(
                    run_id=self.run_id,
                    cpu_percent=float(cpu),
                    memory_rss_bytes=int(mem.rss),
                    memory_vms_bytes=int(mem.vms),
                    thread_count=int(threads),
                    db_path=self.db_path,
                )

                self.sample_count += 1

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                break

            except Exception:
                # Stop if persistence or sampling fails.
                break

    def stop(self, timeout: float = 1.0) -> None:
        """Request shutdown and wait briefly for the worker."""
        self._stop_event.set()

        if self.is_alive():
            self.join(timeout=timeout)


def sample_process_metrics(pid: int) -> Optional[Dict[str, Any]]:
    """
    Return a one-shot resource snapshot for an active PID.

    A single non-blocking CPU sample may be zero because CPU usage needs
    elapsed time between samples. Use ProcessMonitorThread for ongoing
    CPU measurements.
    """
    try:
        proc = psutil.Process(pid)

        if not proc.is_running():
            return None

        if proc.status() == psutil.STATUS_ZOMBIE:
            return None

        mem = proc.memory_info()

        return {
            "pid": pid,
            "cpu_percent": float(proc.cpu_percent(interval=None)),
            "memory_rss_bytes": int(mem.rss),
            "memory_vms_bytes": int(mem.vms),
            "memory_rss_mb": round(
                mem.rss / (1024.0 * 1024.0), 2
            ),
            "thread_count": int(proc.num_threads()),
            "status": proc.status(),
        }

    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
    ):
        return None


def get_host_system_stats() -> Dict[str, Any]:
    """Capture CPU, memory, and disk usage for the WSL2 host."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_total_mb": round(
            vm.total / (1024.0 * 1024.0), 2
        ),
        "memory_used_mb": round(
            vm.used / (1024.0 * 1024.0), 2
        ),
        "memory_available_mb": round(
            vm.available / (1024.0 * 1024.0), 2
        ),
        "memory_percent": float(vm.percent),
        "disk_total_gb": round(
            disk.total / (1024.0 * 1024.0 * 1024.0), 2
        ),
        "disk_free_gb": round(
            disk.free / (1024.0 * 1024.0 * 1024.0), 2
        ),
        "disk_percent": float(disk.percent),
    }
