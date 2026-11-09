"""
Resource Monitoring Component for Portable Sandbox Management System.

Tracks CPU utilization using process CPU-time deltas.
Includes the Bubblewrap process and its visible descendants.
"""

import threading
import time
from typing import Any, Dict, Optional

import psutil

from app.database import log_resource_metric


class ProcessMonitorThread(threading.Thread):
    """Periodically collect process-tree resource metrics."""

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

    def _get_process_tree(self):
        try:
            root = psutil.Process(self.pid)
            processes = [root]
            processes.extend(root.children(recursive=True))

            unique = {}
            for process in processes:
                unique[process.pid] = process

            return list(unique.values())

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    def run(self) -> None:
        previous_cpu = {}

        # Take initial CPU-time readings.
        for process in self._get_process_tree():
            try:
                identity = (process.pid, process.create_time())
                cpu_times = process.cpu_times()
                previous_cpu[identity] = cpu_times.user + cpu_times.system
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                continue

        previous_time = time.monotonic()

        while (
            not self._stop_event.wait(self.interval)
            and self.sample_count < self.max_samples
        ):
            current_time = time.monotonic()
            elapsed = current_time - previous_time

            if elapsed <= 0:
                continue

            processes = self._get_process_tree()

            if not processes:
                break

            current_cpu = {}
            cpu_delta = 0.0
            total_rss = 0
            total_vms = 0
            total_threads = 0
            active_processes = 0

            for process in processes:
                try:
                    if not process.is_running():
                        continue

                    if process.status() == psutil.STATUS_ZOMBIE:
                        continue

                    identity = (process.pid, process.create_time())
                    cpu_times = process.cpu_times()
                    cpu_total = cpu_times.user + cpu_times.system

                    if identity in previous_cpu:
                        delta = cpu_total - previous_cpu[identity]
                        if delta > 0:
                            cpu_delta += delta

                    current_cpu[identity] = cpu_total

                    memory = process.memory_info()
                    total_rss += memory.rss
                    total_vms += memory.vms
                    total_threads += process.num_threads()
                    active_processes += 1

                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    continue

            if active_processes == 0:
                break

            # Percentage relative to one CPU core.
            cpu_percent = (cpu_delta / elapsed) * 100.0

            try:
                log_resource_metric(
                    run_id=self.run_id,
                    cpu_percent=float(cpu_percent),
                    memory_rss_bytes=int(total_rss),
                    memory_vms_bytes=int(total_vms),
                    thread_count=int(total_threads),
                    db_path=self.db_path,
                )

                self.sample_count += 1

            except Exception as error:
                print(
                    f"[MONITOR ERROR] Run {self.run_id}: {error}",
                    flush=True,
                )
                break

            previous_cpu = current_cpu
            previous_time = current_time

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()

        if self.is_alive():
            self.join(timeout=timeout)


def sample_process_metrics(pid: int) -> Optional[Dict[str, Any]]:
    """Return a one-shot resource snapshot for a process tree."""

    try:
        root = psutil.Process(pid)
        processes = [root]
        processes.extend(root.children(recursive=True))

        total_rss = 0
        total_vms = 0
        total_threads = 0

        for process in processes:
            try:
                if not process.is_running():
                    continue

                memory = process.memory_info()
                total_rss += memory.rss
                total_vms += memory.vms
                total_threads += process.num_threads()

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                continue

        return {
            "pid": pid,
            "cpu_percent": 0.0,
            "memory_rss_bytes": total_rss,
            "memory_vms_bytes": total_vms,
            "memory_rss_mb": round(
                total_rss / (1024.0 * 1024.0), 2
            ),
            "thread_count": total_threads,
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
