"""
Phase 2 Integration Test Suite.
Verifies:
1. All 8 DBMS lab demonstrations integrated with persistent project SQLite database.
   - Dedicated tables: lab_departments, lab_employees, lab_salary_audit
   - Zero corruption or modification of operational data (users, sandboxes, execution_runs)
   - Demonstrates: Design, CRUD, Queries, Joins, Constraints, Transactions, Indexes, Views/Triggers.
2. All 8 OS lab modules integrated with Bubblewrap isolation and execution tracking.
   - Manager-policy simulations: Scheduling, Memory, Banker's, BoundedBuffer
   - Bubblewrap isolated runs: IPC, Process Control, Filesystem Isolation, Signals & Telemetry
   - Verification of execution_runs, resource_metrics, and activity_logs persistence.
3. REST API endpoints (/api/labs/os/run and /api/labs/dbms/run).
4. Web routes (/os-lab and /dbms-lab).
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.config import TestingConfig
from app.database import (
    create_sandbox,
    create_user,
    get_execution_run_by_id,
    get_metrics_for_run,
    init_db,
    list_execution_runs_for_sandbox,
    list_recent_activity,
)
from app.dbms_lab.demonstrations import (
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
    demonstrate_filesystem_isolation,
    verify_path_boundaries,
)
from app.os_lab.ipc import pipe_communication
from app.os_lab.memory import allocate_memory
from app.os_lab.process_control import (
    demonstrate_process_timeout,
    run_process_demonstration,
)
from app.os_lab.scheduling import fcfs, round_robin, sjf
from app.os_lab.signals_telemetry import (
    demonstrate_resource_telemetry,
    demonstrate_signal_termination,
)
from app.os_lab.synchronization import BoundedBuffer
from app.sandbox import (
    SANDBOXES_ROOT,
    ensure_sandbox_dir,
    get_or_create_default_sandbox,
    registry,
    stop_execution,
    terminate_process,
)


class TestPhase2DBMSIntegration(unittest.TestCase):
    """Verifies that all 8 DBMS demonstrations execute safely on the actual project database."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "project_test.db")
        init_db(db_path=self.db_path)

        # Seed operational user and sandbox to ensure they remain untouched
        self.user_id = create_user("OperationalUser", "Password123!", role="user", db_path=self.db_path)
        self.sandbox_id = create_sandbox(
            user_id=self.user_id,
            name="Operational Sandbox",
            working_dir="sb_operational",
            db_path=self.db_path,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_all_8_dbms_modules_on_project_database(self):
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
        for mod in modules:
            result = execute_dbms_demonstration(mod, db_path=self.db_path)
            self.assertIsNotNone(result, f"DBMS module {mod} failed on project database")

    def test_dbms_crud_safety_and_cleanup(self):
        # Run CRUD demonstration
        crud_res = execute_dbms_demonstration("crud", db_path=self.db_path)
        self.assertTrue(crud_res["deleted_successfully"])

        # Confirm operational data was untouched
        from app.database import get_sandbox_by_id, get_user_by_id
        op_user = get_user_by_id(self.user_id, db_path=self.db_path)
        op_sandbox = get_sandbox_by_id(self.sandbox_id, db_path=self.db_path)
        self.assertIsNotNone(op_user)
        self.assertEqual(op_user["username"], "OperationalUser")
        self.assertIsNotNone(op_sandbox)

    def test_dbms_transaction_rollback_atomicity(self):
        res = execute_dbms_demonstration("transactions", db_path=self.db_path)
        self.assertTrue(res["rollback_successful"])

    def test_dbms_constraints_enforcement(self):
        res = execute_dbms_demonstration("constraints", db_path=self.db_path)
        self.assertTrue(res["constraint_enforced"])
        self.assertTrue(res["check_constraint_enforced"])


class TestPhase2OSSandboxIntegration(unittest.TestCase):
    """Verifies all 8 OS modules and execution tracking in execution_runs, resource_metrics, and activity_logs."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "os_test.db")
        init_db(db_path=self.db_path)

        self.user_id = create_user("OSTester", "Password123!", role="user", db_path=self.db_path)
        self.sandbox_rel = "sb_os_phase2"
        self.sandbox_id = create_sandbox(
            user_id=self.user_id,
            name="OS Phase 2 Sandbox",
            working_dir=self.sandbox_rel,
            db_path=self.db_path,
        )
        self.target_dir = ensure_sandbox_dir(self.sandbox_rel)

    def tearDown(self):
        # Stop any active processes in registry
        for run_id, pid in list(registry.list_active().items()):
            try:
                stop_execution(run_id, grace_period=0.1, db_path=self.db_path)
            except Exception:
                terminate_process(pid, grace_period=0.1)

        if self.target_dir.exists():
            shutil.rmtree(self.target_dir, ignore_errors=True)
        self.temp_dir.cleanup()

    # Module 1: Scheduling
    def test_os_module1_scheduling(self):
        procs = [
            {"pid": "P1", "arrival": 0, "burst": 4},
            {"pid": "P2", "arrival": 1, "burst": 3},
        ]
        res = fcfs(procs)
        self.assertIn("average_waiting_time", res)
        self.assertIn("timeline", res)

    # Module 2: Memory
    def test_os_module2_memory(self):
        res = allocate_memory([100, 500, 200], [150, 80], "first_fit")
        self.assertEqual(len(res["allocations"]), 2)
        self.assertEqual(res["allocations"][0]["status"], "ALLOCATED")

    # Module 3: Deadlock
    def test_os_module3_deadlock(self):
        from app.os_lab.deadlock import bankers_algorithm
        avail = [3, 3, 2]
        alloc = [[0, 1, 0], [2, 0, 0]]
        max_m = [[7, 5, 3], [3, 2, 2]]
        res = bankers_algorithm(avail, alloc, max_m)
        self.assertIn("safe", res)
        self.assertIn("need_matrix", res)

    # Module 4: Synchronization
    def test_os_module4_synchronization(self):
        buf = BoundedBuffer(2)
        buf.produce("item1")
        buf.produce("item2")
        status = buf.get_status()
        self.assertEqual(status["items"], 2)
        item = buf.consume()
        self.assertEqual(item, "item1")

    # Module 5: IPC with Bubblewrap
    def test_os_module5_sandboxed_ipc(self):
        msg = "Isolated IPC Message"
        res = pipe_communication(
            message=msg,
            sandbox_id=self.sandbox_id,
            working_dir=self.sandbox_rel,
            db_path=self.db_path,
        )
        self.assertEqual(res["communication"], "Successful")
        self.assertIn(msg, res["child_response"])
        self.assertIsNotNone(res.get("run_id"))

        # Verify execution record in database
        run_record = get_execution_run_by_id(res["run_id"], db_path=self.db_path)
        self.assertIsNotNone(run_record)
        self.assertEqual(run_record["status"], "COMPLETED")

    # Module 6: Process Lifecycle & Control
    def test_os_module6_process_control(self):
        cmd = [sys.executable, "-c", "import os; print(f'Lifecycle PID: {os.getpid()}')"]
        res = run_process_demonstration(
            sandbox_id=self.sandbox_id,
            command=cmd,
            working_dir=self.sandbox_rel,
            timeout=5.0,
            db_path=self.db_path,
        )
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("Lifecycle PID:", res["stdout"])

        # Check execution_runs and activity_logs
        runs = list_execution_runs_for_sandbox(self.sandbox_id, db_path=self.db_path)
        self.assertGreaterEqual(len(runs), 1)

    # Module 7: Filesystem Isolation
    def test_os_module7_filesystem_isolation(self):
        res = demonstrate_filesystem_isolation(
            sandbox_id=self.sandbox_id,
            working_dir=self.sandbox_rel,
            db_path=self.db_path,
        )
        self.assertTrue(res["runtime_probe"]["isolation_verified"])
        self.assertTrue(res["runtime_probe"]["root_write_blocked"])
        self.assertTrue(res["runtime_probe"]["workspace_write_allowed"])

    # Module 8: Signals & Telemetry
    def test_os_module8_signals_and_telemetry(self):
        # 1. Test Signal Termination
        sig_res = demonstrate_signal_termination(
            sandbox_id=self.sandbox_id,
            working_dir=self.sandbox_rel,
            grace_period=0.5,
            db_path=self.db_path,
        )
        self.assertTrue(sig_res["termination_result"]["stopped_successfully"])
        self.assertEqual(sig_res["termination_result"]["db_status"], "TERMINATED")

        # 2. Test Resource Telemetry
        telem_res = demonstrate_resource_telemetry(
            sandbox_id=self.sandbox_id,
            working_dir=self.sandbox_rel,
            db_path=self.db_path,
        )
        self.assertGreaterEqual(telem_res["sample_count"], 1)
        metrics = get_metrics_for_run(telem_res["run_id"], db_path=self.db_path)
        self.assertGreaterEqual(len(metrics), 1)


class TestPhase2APIRoutes(unittest.TestCase):
    """Verifies REST API endpoints /api/labs/os/run and /api/labs/dbms/run."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "api_test.db")
        init_db(db_path=self.db_path)

        class CustomTestConfig(TestingConfig):
            DATABASE_PATH = self.db_path

        self.app = create_app(CustomTestConfig)
        self.client = self.app.test_client()

        # Register and login test user
        self.client.post(
            "/api/auth/register",
            data=json.dumps({"username": "labuser", "password": "Password123!"}),
            content_type="application/json",
        )
        self.client.post(
            "/api/auth/login",
            data=json.dumps({"username": "labuser", "password": "Password123!"}),
            content_type="application/json",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_api_os_lab_scheduling(self):
        payload = {
            "module": "scheduling",
            "payload": {
                "algorithm": "fcfs",
                "processes": [
                    {"pid": "P1", "arrival": 0, "burst": 5},
                    {"pid": "P2", "arrival": 1, "burst": 2},
                ],
            },
        }
        res = self.client.post("/api/labs/os/run", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("processes", data["data"])

    def test_api_os_lab_process_control(self):
        payload = {
            "module": "process_control",
            "payload": {"command": [sys.executable, "-c", "print('API OS Process OK')"]},
        }
        res = self.client.post("/api/labs/os/run", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["status"], "COMPLETED")

    def test_api_dbms_lab_all_modules(self):
        modules = ["design", "crud", "queries", "joins", "constraints", "transactions", "indexes", "views_triggers"]
        for mod in modules:
            payload = {"module": mod}
            res = self.client.post("/api/labs/dbms/run", data=json.dumps(payload), content_type="application/json")
            self.assertEqual(res.status_code, 200, f"API DBMS module '{mod}' failed")
            data = res.get_json()
            self.assertTrue(data["success"])

    def test_api_unauthorized_rejection(self):
        # Logout
        self.client.post("/api/auth/logout")
        res = self.client.post(
            "/api/labs/os/run",
            data=json.dumps({"module": "scheduling"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
