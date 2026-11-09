"""
Phase 1 Unit & Integration Test Suite.
Verifies:
1. Subprocess-based safe IPC pipe communication (no os.fork() in web worker).
2. Process management and lifecycle control (app/os_lab/process_control.py).
3. Bubblewrap filesystem isolation & path boundary checks (app/os_lab/filesystem_isolation.py).
4. Process signals and resource telemetry monitoring (app/os_lab/signals_telemetry.py).
5. Centralized DBMS demonstration functions across all 8 modules (app/dbms_lab/demonstrations.py).
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import create_sandbox, create_user, init_db
from app.dbms_lab.demonstrations import (
    create_demo_database,
    demonstrate_aggregation,
    demonstrate_constraints,
    demonstrate_crud,
    demonstrate_design,
    demonstrate_index,
    demonstrate_joins,
    demonstrate_queries,
    demonstrate_transaction_rollback,
    demonstrate_views_and_triggers,
    execute_dbms_demonstration,
)
from app.os_lab.filesystem_isolation import (
    inspect_isolation_profile,
    verify_path_boundaries,
)
from app.os_lab.ipc import pipe_communication
from app.os_lab.process_control import (
    demonstrate_process_timeout,
    run_process_demonstration,
)
from app.os_lab.signals_telemetry import (
    demonstrate_resource_telemetry,
    demonstrate_signal_termination,
)
from app.sandbox import SANDBOXES_ROOT, ensure_sandbox_dir


class TestPhase1OSModules(unittest.TestCase):
    def setUp(self):
        """Set up an isolated temporary database and clean sandbox directory."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_phase1.db")
        init_db(db_path=self.db_path)

        self.user_id = create_user("Phase1Tester", "password123", db_path=self.db_path)
        self.sandbox_rel_dir = "sb_phase1_test"
        self.sandbox_id = create_sandbox(
            user_id=self.user_id,
            name="Phase 1 Test Sandbox",
            working_dir=self.sandbox_rel_dir,
            db_path=self.db_path,
        )
        self.target_dir = ensure_sandbox_dir(self.sandbox_rel_dir)

    def tearDown(self):
        """Clean up temporary sandbox files and test database."""
        if self.target_dir.exists():
            shutil.rmtree(self.target_dir, ignore_errors=True)
        self.temp_dir.cleanup()

    # 1. Safe IPC
    def test_safe_subprocess_ipc(self):
        message = "Antigravity Safe IPC Test"
        result = pipe_communication(message)
        self.assertEqual(result["message_sent"], message)
        self.assertEqual(result["communication"], "Successful")
        self.assertEqual(result["method"], "OS pipe")
        self.assertIn("Child received: Antigravity Safe IPC Test", result["child_response"])
        self.assertIsInstance(result["child_pid"], int)

    # 2. Process Control
    def test_process_control_lifecycle(self):
        cmd = [sys.executable, "-c", "print('Process Lifecycle OK')"]
        result = run_process_demonstration(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel_dir,
            timeout=5.0,
            db_path=self.db_path,
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("Process Lifecycle OK", result["stdout"])
        self.assertIsInstance(result["pid"], int)
        self.assertIn("COMPLETED", result["lifecycle_stages"])

    def test_process_control_timeout(self):
        result = demonstrate_process_timeout(
            sandbox_id=self.sandbox_id,
            working_dir=self.sandbox_rel_dir,
            sleep_seconds=5.0,
            timeout=0.4,
            db_path=self.db_path,
        )
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertIn("timed out", result["stderr"].lower())

    # 3. Filesystem Isolation
    def test_path_boundaries(self):
        checks = verify_path_boundaries([
            "sb_valid_path",
            "../../etc/passwd",
            "/tmp",
            ".",
        ])
        status_map = {c["path"]: c["status"] for c in checks}
        self.assertEqual(status_map["sb_valid_path"], "ALLOWED")
        self.assertEqual(status_map["../../etc/passwd"], "BLOCKED")
        self.assertEqual(status_map["/tmp"], "BLOCKED")
        self.assertEqual(status_map["."], "BLOCKED")

    def test_isolation_profile_metadata(self):
        profile = inspect_isolation_profile(self.target_dir)
        self.assertEqual(profile["isolation_engine"], "bubblewrap (bwrap)")
        self.assertTrue(any("CLONE_NEWPID" in ns for ns in profile["unshared_namespaces"]))
        self.assertIn("root_filesystem", profile["mount_policies"])
        self.assertIn("Read-Only", profile["mount_policies"]["root_filesystem"])

    # 4. Signals & Telemetry
    def test_signals_termination(self):
        result = demonstrate_signal_termination(
            sandbox_id=self.sandbox_id,
            working_dir=self.sandbox_rel_dir,
            grace_period=0.5,
            db_path=self.db_path,
        )
        self.assertTrue(result["initial_state"]["pid_exists"])
        self.assertTrue(result["termination_result"]["stopped_successfully"])
        self.assertFalse(result["termination_result"]["pid_still_exists"])
        self.assertEqual(result["termination_result"]["db_status"], "TERMINATED")

    def test_resource_telemetry_accounting(self):
        result = demonstrate_resource_telemetry(
            sandbox_id=self.sandbox_id,
            working_dir=self.sandbox_rel_dir,
            db_path=self.db_path,
        )
        self.assertIsInstance(result["pid"], int)
        self.assertGreaterEqual(result["sample_count"], 1)
        self.assertIn("cpu_percent", result["host_system_stats"])
        self.assertIn("memory_total_mb", result["host_system_stats"])


class TestPhase1DBMSModules(unittest.TestCase):
    def setUp(self):
        self.conn = create_demo_database()

    def tearDown(self):
        self.conn.close()

    def test_demonstrate_design(self):
        tables = demonstrate_design(self.conn)
        names = {t["name"] for t in tables}
        self.assertIn("departments", names)
        self.assertIn("employees", names)
        self.assertIn("employee_department_view", names)

    def test_demonstrate_crud(self):
        crud_res = demonstrate_crud(self.conn)
        self.assertEqual(crud_res["after_insert_and_update"]["employee_id"], 105)
        self.assertEqual(crud_res["after_insert_and_update"]["salary"], 48000)
        self.assertTrue(crud_res["deleted_successfully"])

    def test_demonstrate_queries_and_aggregation(self):
        queries_res = demonstrate_queries(self.conn)
        self.assertTrue(all(r["salary"] >= 50000 for r in queries_res))

        agg_res = demonstrate_aggregation(self.conn)
        self.assertGreaterEqual(len(agg_res), 1)
        self.assertIn("employee_count", agg_res[0])
        self.assertIn("average_salary", agg_res[0])

    def test_demonstrate_joins(self):
        joins_res = demonstrate_joins(self.conn)
        self.assertGreaterEqual(len(joins_res), 1)
        self.assertIn("employee_name", joins_res[0])
        self.assertIn("department_name", joins_res[0])

    def test_demonstrate_constraints(self):
        res = demonstrate_constraints(self.conn)
        self.assertTrue(res["constraint_enforced"])

    def test_demonstrate_transaction_rollback(self):
        rollback_success = demonstrate_transaction_rollback(self.conn)
        self.assertTrue(rollback_success)

    def test_demonstrate_index(self):
        indexes = demonstrate_index(self.conn)
        names = [idx["name"] for idx in indexes]
        self.assertIn("idx_employee_department", names)

    def test_demonstrate_views_and_triggers(self):
        res = demonstrate_views_and_triggers(self.conn)
        self.assertIn("view", res)
        self.assertIn("trigger_audit", res)
        self.assertGreater(len(res["view"]), 0)
        self.assertEqual(len(res["trigger_audit"]), 1)
        self.assertEqual(res["trigger_audit"][0]["employee_id"], 101)
        self.assertEqual(res["trigger_audit"][0]["old_salary"], 50000)
        self.assertEqual(res["trigger_audit"][0]["new_salary"], 52000)

    def test_central_dispatcher_all_8_modules(self):
        modules = [
            "design",
            "crud",
            "queries",
            "joins",
            "constraints",
            "transactions",
            "indexes",
            "views_triggers",
        ]
        for m in modules:
            res = execute_dbms_demonstration(m)
            self.assertIsNotNone(res, f"Module '{m}' returned None from central dispatcher")

        with self.assertRaises(ValueError):
            execute_dbms_demonstration("non_existent_module")


if __name__ == "__main__":
    unittest.main(verbosity=2)

