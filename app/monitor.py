"""
Resource Monitoring Component for Portable Sandbox Management System.
Demonstrates Operating Systems & telemetry concepts:
- Non-invasive resource tracking using psutil and the /proc filesystem
- Process accounting: CPU utilization percentage, RSS (Resident Set Size) memory,
  VMS (Virtual Memory Size), and active thread count
- Asynchronous periodic background sampling thread
- Database persistence via the existing DBMS layer (app.database.log_resource_metric)
- System health reporting for host WSL2 Linux environment
"""

import threading
import time
from typing import Any, Dict, Optional
import psutil

from app.database import log_resource_metric


class ProcessMonitorThread(threading.Thread):
    """
    Background worker thread that periodically polls a supervised process
    and persists CPU, memory, and thread metrics to the database.
    """

    def __init__(
        self,
        pid: int,
        run_id: int,
        interval: float = 0.2,
        db_path: Optional[str] = None,
        max_samples: int = 1000
    ):
        super().__init__(name=f"Monitor-PID-{pid}", daemon=True)
        self.pid = pid
        self.run_id = run_id
        self.interval = max(0.05, interval)
        self.db_path = db_path
        self.max_samples = max_samples
        self._stop_event = threading.Event()
        self.sample_count = 0

    def run(self) -> None:
        """Main sampling loop."""
        try:
            proc = psutil.Process(self.pid)
            # Initial call to cpu_percent primes the counter
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return

        while not self._stop_event.is_set() and self.sample_count < self.max_samples:
            # Wait for interval or stop event
            if self._stop_event.wait(self.interval):
                break

            try:
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    break

                cpu = proc.cpu_percent(interval=None)
                mem = proc.memory_info()
                threads = proc.num_threads()

                log_resource_metric(
                    run_id=self.run_id,
                    cpu_percent=float(cpu),
                    memory_rss_bytes=int(mem.rss),
                    memory_vms_bytes=int(mem.vms),
                    thread_count=int(threads),
                    db_path=self.db_path
                )
                self.sample_count += 1

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                break
            except Exception:
                # Keep thread resilient against unexpected database lock timeouts
                break

    def stop(self, timeout: float = 1.0) -> None:
        """Signals the monitoring thread to stop and waits for completion."""
        self._stop_event.set()
        self.join(timeout=timeout)


def sample_process_metrics(pid: int) -> Optional[Dict[str, Any]]:
    """
    Performs a synchronous, one-shot telemetry sample of a specific PID.
    Returns dictionary with CPU, RSS, VMS, and thread count, or None if inactive.
    """
    try:
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return None

        mem = proc.memory_info()
        return {
            "pid": pid,
            "cpu_percent": float(proc.cpu_percent(interval=None)),
            "memory_rss_bytes": int(mem.rss),
            "memory_vms_bytes": int(mem.vms),
            "memory_rss_mb": round(mem.rss / (1024.0 * 1024.0), 2),
            "thread_count": int(proc.num_threads()),
            "status": proc.status(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def get_host_system_stats() -> Dict[str, Any]:
    """
    Captures host system resource utilization (WSL2 Ubuntu environment).
    Useful for system status cards in dashboard.
    """
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_total_mb": round(vm.total / (1024.0 * 1024.0), 2),
        "memory_used_mb": round(vm.used / (1024.0 * 1024.0), 2),
        "memory_available_mb": round(vm.available / (1024.0 * 1024.0), 2),
        "memory_percent": float(vm.percent),
        "disk_total_gb": round(disk.total / (1024.0 * 1024.0 * 1024.0), 2),
        "disk_free_gb": round(disk.free / (1024.0 * 1024.0 * 1024.0), 2),
        "disk_percent": float(disk.percent),
    }
