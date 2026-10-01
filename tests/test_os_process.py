"""
Unit and Integration Tests for OS Process Engine & Resource Monitoring.
Demonstrates:
- Path validation and path traversal prevention (security boundary)
- Command tokenization and safe execution (shell=False)
- Process lifecycle: execution, output capture, exit code tracking
- Process timeout enforcement
- Graceful termination (SIGTERM) and forceful termination (SIGKILL escalation)
- Resource telemetry integration via psutil and SQLite persistence
- Reliable multi-connection database testing using an isolated TemporaryDirectory (cleaned up on teardown)
"""

import os
import shutil
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psutil

from app.database import (
    create_sandbox,
    create_user,
    get_execution_run_by_id,
    get_metrics_for_run,
    init_db,
)
from app.monitor import get_host_system_stats, sample_process_metrics
from app.sandbox import (
    SANDBOXES_ROOT,
    execute_sync,
    registry,
    sanitize_command,
    spawn_process,
    stop_execution,
    terminate_process,
    validate_sandbox_path,
)


class TestOSProcessEngine(unittest.TestCase):
    def setUp(self):
        """Setup isolated temporary database and clean sandbox directory."""
        # Use TemporaryDirectory to ensure multi-threaded monitor can access the exact same DB
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_os_process.db")

        # Initialize schema in temporary database
        init_db(db_path=self.db_path)

        # Seed test user and sandbox
        self.user_id = create_user("ProcessTester", "password123", db_path=self.db_path)
        self.sandbox_rel_dir = "sb_test_os"
        self.sandbox_id = create_sandbox(
            user_id=self.user_id,
            name="OS Test Sandbox",
            working_dir=self.sandbox_rel_dir,
            db_path=self.db_path
        )
        self.target_dir = SANDBOXES_ROOT / self.sandbox_rel_dir
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Ensure no zombie processes and clean up temporary test resources."""
        # 1. Terminate any lingering processes in registry
        active = registry.list_active()
        for run_id, pid in active.items():
            try:
                stop_execution(run_id, grace_period=0.2, db_path=self.db_path)
            except Exception:
                terminate_process(pid, grace_period=0.1)

        # 2. Clean up test sandbox directory
        if self.target_dir.exists():
            shutil.rmtree(self.target_dir, ignore_errors=True)

        # 3. Clean up temporary database directory
        self.temp_dir.cleanup()

    # ----------------------------------------------------
    # 1. Path Validation & Traversal Tests
    # ----------------------------------------------------
    def test_path_validation_and_traversal_rejection(self):
        # Valid path inside sandboxes/
        valid = validate_sandbox_path("sb_test_valid")
        self.assertTrue(valid.is_relative_to(SANDBOXES_ROOT))

        # Direct targeting of sandboxes root must be rejected
        with self.assertRaises(ValueError):
            validate_sandbox_path(SANDBOXES_ROOT)

        with self.assertRaises(ValueError):
            validate_sandbox_path(".")

        # Directory traversal attempts must be rejected
        with self.assertRaises(ValueError):
            validate_sandbox_path("../")

        with self.assertRaises(ValueError):
            validate_sandbox_path("sb_test/../../etc")

        with self.assertRaises(ValueError):
            validate_sandbox_path("/etc/passwd")

        with self.assertRaises(ValueError):
            validate_sandbox_path("/tmp")

    # ----------------------------------------------------
    # 2. Command Sanitization Tests
    # ----------------------------------------------------
    def test_command_sanitization(self):
        tokens = sanitize_command("python3 -c 'print(123)'")
        self.assertEqual(tokens, ["python3", "-c", "print(123)"])

        # Shell operators must NOT be expanded; they become literal argv arguments
        tokens_shell = sanitize_command("echo hello; rm -rf /")
        self.assertEqual(tokens_shell, ["echo", "hello;", "rm", "-rf", "/"])

        # Empty commands must be rejected
        with self.assertRaises(ValueError):
            sanitize_command("")

        with self.assertRaises(ValueError):
            sanitize_command("   ")

    # ----------------------------------------------------
    # 3. Process Lifecycle: Output & Exit Code Capture
    # ----------------------------------------------------
    def test_process_sync_lifecycle_and_output_capture(self):
        cmd = [sys.executable, "-c", "print('Antigravity Sandbox Output')"]
        run_record = execute_sync(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel_dir,
            db_path=self.db_path
        )

        self.assertEqual(run_record["status"], "COMPLETED")
        self.assertEqual(run_record["exit_code"], 0)
        self.assertIn("Antigravity Sandbox Output", run_record["stdout"])
        self.assertEqual(run_record["stderr"], "")
        self.assertIsNotNone(run_record["pid"])
        self.assertIsNotNone(run_record["start_time"])
        self.assertIsNotNone(run_record["end_time"])

    def test_process_failure_and_stderr_capture(self):
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('Expected failure test'); sys.exit(9)"]
        run_record = execute_sync(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel_dir,
            db_path=self.db_path
        )

        self.assertEqual(run_record["status"], "FAILED")
        self.assertEqual(run_record["exit_code"], 9)
        self.assertIn("Expected failure test", run_record["stderr"])

    # ----------------------------------------------------
    # 4. Timeout Enforcement
    # ----------------------------------------------------
    def test_process_timeout_enforcement(self):
        cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
        start = time.time()
        run_record = execute_sync(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel_dir,
            timeout=0.5,
            db_path=self.db_path
        )
        elapsed = time.time() - start

        self.assertLess(elapsed, 3.0, "Process should be killed promptly upon timeout")
        self.assertEqual(run_record["status"], "TIMED_OUT")
        self.assertIn("timed out", run_record["stderr"].lower())
        # Confirm PID is no longer running in OS
        pid = run_record["pid"]
        self.assertFalse(psutil.pid_exists(pid))

    # ----------------------------------------------------
    # 5. Graceful Termination (SIGTERM)
    # ----------------------------------------------------
    def test_graceful_termination_sigterm(self):
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        run_id, proc = spawn_process(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel_dir,
            db_path=self.db_path
        )
        pid = proc.pid
        self.assertTrue(psutil.pid_exists(pid))

        # Request termination
        stopped = stop_execution(run_id=run_id, grace_period=1.5, db_path=self.db_path)
        self.assertTrue(stopped)

        # Verify database record
        record = get_execution_run_by_id(run_id, db_path=self.db_path)
        self.assertEqual(record["status"], "TERMINATED")
        self.assertIsNotNone(record["end_time"])

        # Verify OS process is gone
        time.sleep(0.1)
        self.assertFalse(psutil.pid_exists(pid), "Process must be terminated in OS")

    # ----------------------------------------------------
    # 6. Forceful Termination (SIGKILL Escalation)
    # ----------------------------------------------------
    def test_forceful_termination_sigkill(self):
        # Process that traps and ignores SIGTERM
        code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        cmd = [sys.executable, "-c", code]

        run_id, proc = spawn_process(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel_dir,
            db_path=self.db_path
        )
        pid = proc.pid
        self.assertTrue(psutil.pid_exists(pid))

        # stop_execution will try SIGTERM, wait grace_period, then escalate to SIGKILL
        start = time.time()
        stopped = stop_execution(run_id=run_id, grace_period=0.4, db_path=self.db_path)
        elapsed = time.time() - start

        self.assertTrue(stopped)
        self.assertLess(elapsed, 3.0, "SIGKILL escalation should complete within reasonable window")

        record = get_execution_run_by_id(run_id, db_path=self.db_path)
        self.assertEqual(record["status"], "TERMINATED")

        # Confirm PID is killed
        time.sleep(0.1)
        self.assertFalse(psutil.pid_exists(pid), "Process ignoring SIGTERM must be killed by SIGKILL")

    # ----------------------------------------------------
    # 7. Resource Monitoring Integration
    # ----------------------------------------------------
    def test_resource_monitoring_integration(self):
        # Workload running for ~0.8s
        code = "import time; [time.sleep(0.08) for _ in range(10)]"
        cmd = [sys.executable, "-c", code]

        run_id, proc = spawn_process(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel_dir,
            enable_monitoring=True,
            db_path=self.db_path
        )

        # Wait for process to finish
        proc.wait(timeout=5.0)
        time.sleep(0.3)  # brief pause to allow monitor loop to complete last iteration

        # Stop monitor and update DB
        stop_execution(run_id=run_id, db_path=self.db_path)

        # Check metrics table in SQLite
        metrics = get_metrics_for_run(run_id=run_id, db_path=self.db_path)
        self.assertGreaterEqual(
            len(metrics),
            1,
            "Resource monitor must record at least 1 metric sample during execution."
        )

        sample = metrics[0]
        self.assertGreaterEqual(sample["cpu_percent"], 0.0)
        self.assertGreater(sample["memory_rss_bytes"], 0, "RSS memory must be positive integer")
        self.assertGreater(sample["memory_vms_bytes"], 0, "VMS memory must be positive integer")
        self.assertGreaterEqual(sample["thread_count"], 1, "Thread count must be at least 1")

    # ----------------------------------------------------
    # 8. Host System Stats & One-shot Telemetry
    # ----------------------------------------------------
    def test_host_system_stats_and_telemetry(self):
        stats = get_host_system_stats()
        self.assertIn("cpu_percent", stats)
        self.assertIn("memory_total_mb", stats)
        self.assertIn("memory_used_mb", stats)
        self.assertIn("disk_free_gb", stats)
        self.assertGreater(stats["memory_total_mb"], 0)

        # One-shot PID sample on current process
        pid_sample = sample_process_metrics(os.getpid())
        self.assertIsNotNone(pid_sample)
        self.assertEqual(pid_sample["pid"], os.getpid())
        self.assertGreater(pid_sample["memory_rss_bytes"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
