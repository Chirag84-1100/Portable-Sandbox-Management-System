"""
Comprehensive Automated Integration Tests for Flask REST API Layer.
Demonstrates:
- Public registration with fixed 'user' role (role escalation rejection)
- Session authentication, login, logout, and protected route guards
- Multi-tenant authorization boundaries (User A vs User B cross-tenant isolation)
- Sandbox CRUD operations and analytics
- Process execution (synchronous and asynchronous), stream capture, and termination
- Telemetry metrics retrieval and host system health reporting
- Uniform JSON error response formatting
- Zero persistent production database usage (runs in tempfile.TemporaryDirectory)
"""

import json
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
from app.database import get_user_by_username, init_db
from app.sandbox import SANDBOXES_ROOT, registry, stop_execution, terminate_process


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        """Initializes an isolated temporary database and Flask test client."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_api.db")

        # Initialize schema into the temporary database
        init_db(db_path=self.db_path)

        class CustomTestConfig(TestingConfig):
            DATABASE_PATH = self.db_path

        self.app = create_app(CustomTestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        """Cleans up active processes, temporary sandbox directories, and temp database."""
        # 1. Terminate any active background processes
        active = registry.list_active()
        for run_id, pid in active.items():
            try:
                stop_execution(run_id, grace_period=0.1, db_path=self.db_path)
            except Exception:
                terminate_process(pid, grace_period=0.1)

        # 2. Clean up any created sandbox directories in sandboxes/
        for p in list(SANDBOXES_ROOT.glob("sb_*")) + list((SANDBOXES_ROOT / "sandboxes").glob("sb_*")):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        sub_root = SANDBOXES_ROOT / "sandboxes"
        if sub_root.is_dir() and not any(sub_root.iterdir()):
            sub_root.rmdir()

        # 3. Clean up temporary directory
        self.temp_dir.cleanup()

    # ----------------------------------------------------
    # Helper methods
    # ----------------------------------------------------
    def register(self, username, password, extra_data=None):
        payload = {"username": username, "password": password}
        if extra_data:
            payload.update(extra_data)
        return self.client.post(
            "/api/auth/register",
            data=json.dumps(payload),
            content_type="application/json"
        )

    def login(self, username, password):
        return self.client.post(
            "/api/auth/login",
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json"
        )

    def logout(self):
        return self.client.post("/api/auth/logout")

    # ----------------------------------------------------
    # 1. Authentication & Security Tests
    # ----------------------------------------------------
    def test_registration_always_assigns_user_role(self):
        """SECURITY: Client cannot escalate privileges by sending role='admin' in registration."""
        res = self.register("attacker", "Password123!", extra_data={"role": "admin"})
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        # Verify role is strictly 'user'
        self.assertEqual(data["data"]["role"], "user", "Public registration must strictly assign role='user'")

        # Verify directly in the SQLite database record
        user_record = get_user_by_username("attacker", db_path=self.db_path)
        self.assertIsNotNone(user_record)
        self.assertEqual(user_record["role"], "user", "Database record must strictly store role='user'")

        # Verify session and /api/auth/me profile report role='user'
        self.login("attacker", "Password123!")
        me_res = self.client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.get_json()["data"]["user"]["role"], "user")
        self.logout()

    def test_registration_validation_and_duplicate(self):
        # Empty username
        res = self.register("", "Password123!")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])

        # Short password
        res = self.register("validuser", "123")
        self.assertEqual(res.status_code, 400)

        # Successful registration
        res1 = self.register("alice", "Password123!")
        self.assertEqual(res1.status_code, 201)

        # Duplicate username (case-insensitive)
        res2 = self.register("Alice", "AnotherPassword123!")
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.get_json()["error"]["code"], "CONFLICT")

    def test_login_success_and_session(self):
        self.register("bob", "Password123!")

        # Correct login
        res = self.login("bob", "Password123!")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["user"]["username"], "bob")

        # Verify current session via /api/auth/me
        me_res = self.client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.get_json()["data"]["user"]["username"], "bob")

    def test_login_failure(self):
        self.register("charlie", "Password123!")

        # Wrong password
        res = self.login("charlie", "WrongPassword!")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["error"]["code"], "UNAUTHORIZED")

        # Nonexistent user
        res = self.login("nobody", "Password123!")
        self.assertEqual(res.status_code, 401)

    def test_logout(self):
        self.register("dave", "Password123!")
        self.login("dave", "Password123!")

        # Logout
        logout_res = self.logout()
        self.assertEqual(logout_res.status_code, 200)

        # Subsequent /api/auth/me must return 401
        me_res = self.client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, 401)

    def test_protected_routes_require_login(self):
        # Access without login
        res = self.client.get("/api/sandboxes")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["error"]["code"], "UNAUTHORIZED")

    # ----------------------------------------------------
    # 2. Sandbox CRUD & Analytics Tests
    # ----------------------------------------------------
    def test_sandbox_crud_operations(self):
        self.register("eve", "Password123!")
        self.login("eve", "Password123!")

        # Create sandbox
        create_res = self.client.post(
            "/api/sandboxes",
            data=json.dumps({"name": "Test Sandbox Eve", "description": "Workspace for Eve"}),
            content_type="application/json"
        )
        self.assertEqual(create_res.status_code, 201)
        sb_data = create_res.get_json()["data"]
        sandbox_id = sb_data["id"]
        self.assertEqual(sb_data["name"], "Test Sandbox Eve")

        # Duplicate sandbox name for same user rejected
        dup_res = self.client.post(
            "/api/sandboxes",
            data=json.dumps({"name": "Test Sandbox Eve"}),
            content_type="application/json"
        )
        self.assertEqual(dup_res.status_code, 409)

        # List sandboxes
        list_res = self.client.get("/api/sandboxes")
        self.assertEqual(list_res.status_code, 200)
        sandboxes = list_res.get_json()["data"]
        self.assertEqual(len(sandboxes), 1)

        # Get specific sandbox
        get_res = self.client.get(f"/api/sandboxes/{sandbox_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.get_json()["data"]["id"], sandbox_id)

        # Update sandbox
        update_res = self.client.put(
            f"/api/sandboxes/{sandbox_id}",
            data=json.dumps({"description": "Updated description"}),
            content_type="application/json"
        )
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.get_json()["data"]["description"], "Updated description")

        # Get analytics
        analytics_res = self.client.get(f"/api/sandboxes/{sandbox_id}/analytics")
        self.assertEqual(analytics_res.status_code, 200)

        # Delete sandbox
        del_res = self.client.delete(f"/api/sandboxes/{sandbox_id}")
        self.assertEqual(del_res.status_code, 200)

        # Verify deletion
        get_after = self.client.get(f"/api/sandboxes/{sandbox_id}")
        self.assertEqual(get_after.status_code, 404)

    # ----------------------------------------------------
    # 3. Multi-Tenant Authorization & Ownership Isolation
    # ----------------------------------------------------
    def test_authorization_isolation_between_users(self):
        # 1. User A creates a sandbox
        self.register("user_a", "Password123!")
        self.login("user_a", "Password123!")
        res_a = self.client.post(
            "/api/sandboxes",
            data=json.dumps({"name": "User A Private Sandbox"}),
            content_type="application/json"
        )
        sandbox_a_id = res_a.get_json()["data"]["id"]
        self.logout()

        # 2. User B logs in
        self.register("user_b", "Password123!")
        self.login("user_b", "Password123!")

        # User B cannot access User A's sandbox
        res = self.client.get(f"/api/sandboxes/{sandbox_a_id}")
        self.assertEqual(res.status_code, 403, "User B must not access User A's sandbox")
        self.assertEqual(res.get_json()["error"]["code"], "FORBIDDEN")

        # User B cannot update User A's sandbox
        res = self.client.put(
            f"/api/sandboxes/{sandbox_a_id}",
            data=json.dumps({"name": "Hacked Sandbox"}),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 403)

        # User B cannot delete User A's sandbox
        res = self.client.delete(f"/api/sandboxes/{sandbox_a_id}")
        self.assertEqual(res.status_code, 403)

        # User B cannot execute commands in User A's sandbox
        res = self.client.post(
            f"/api/sandboxes/{sandbox_a_id}/execute",
            data=json.dumps({"command": "echo test"}),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 403)

    # ----------------------------------------------------
    # 4. Process Execution & Telemetry Endpoints
    # ----------------------------------------------------
    def test_execution_api_sync_and_async(self):
        self.register("executor", "Password123!")
        self.login("executor", "Password123!")

        # Create sandbox
        sb_res = self.client.post(
            "/api/sandboxes",
            data=json.dumps({"name": "Execution Sandbox"}),
            content_type="application/json"
        )
        sandbox_id = sb_res.get_json()["data"]["id"]

        # 1. Synchronous Execution
        sync_res = self.client.post(
            f"/api/sandboxes/{sandbox_id}/execute",
            data=json.dumps({
                "command": [sys.executable, "-c", "print('API Execution Test')"],
                "async": False
            }),
            content_type="application/json"
        )
        self.assertEqual(sync_res.status_code, 200)
        sync_data = sync_res.get_json()["data"]
        self.assertEqual(sync_data["status"], "COMPLETED")
        self.assertIn("API Execution Test", sync_data["stdout"])
        run_id = sync_data["id"]

        # Retrieve execution details
        get_run = self.client.get(f"/api/executions/{run_id}")
        self.assertEqual(get_run.status_code, 200)
        self.assertEqual(get_run.get_json()["data"]["id"], run_id)

        # 2. Asynchronous Execution and Stopping
        async_res = self.client.post(
            f"/api/sandboxes/{sandbox_id}/execute",
            data=json.dumps({
                "command": [sys.executable, "-c", "import time; time.sleep(30)"],
                "async": True
            }),
            content_type="application/json"
        )
        self.assertEqual(async_res.status_code, 201)
        async_data = async_res.get_json()["data"]
        async_run_id = async_data["run_id"]
        self.assertEqual(async_data["status"], "RUNNING")
        self.assertGreater(async_data["pid"], 0)

        # Stop active execution
        stop_res = self.client.post(
            f"/api/executions/{async_run_id}/stop",
            data=json.dumps({"grace_period": 0.5}),
            content_type="application/json"
        )
        self.assertEqual(stop_res.status_code, 200)
        stopped_data = stop_res.get_json()["data"]
        self.assertEqual(stopped_data["status"], "TERMINATED")

    def test_metrics_and_system_stats(self):
        self.register("stats_user", "Password123!")
        self.login("stats_user", "Password123!")

        # Create sandbox
        sb_res = self.client.post(
            "/api/sandboxes",
            data=json.dumps({"name": "Stats Sandbox"}),
            content_type="application/json"
        )
        sandbox_id = sb_res.get_json()["data"]["id"]

        # Run process with monitoring enabled
        exec_res = self.client.post(
            f"/api/sandboxes/{sandbox_id}/execute",
            data=json.dumps({
                "command": [sys.executable, "-c", "import time; [time.sleep(0.08) for _ in range(10)]"],
                "async": True,
                "enable_monitoring": True
            }),
            content_type="application/json"
        )
        run_id = exec_res.get_json()["data"]["run_id"]

        # Wait briefly for execution and metrics capture
        time.sleep(1.2)
        self.client.post(f"/api/executions/{run_id}/stop", data=json.dumps({"grace_period": 0.2}), content_type="application/json")

        # Query metrics endpoint
        metrics_res = self.client.get(f"/api/executions/{run_id}/metrics")
        self.assertEqual(metrics_res.status_code, 200)
        metrics = metrics_res.get_json()["data"]
        self.assertIsInstance(metrics, list)
        self.assertGreaterEqual(len(metrics), 1, "Metrics endpoint must return at least 1 recorded sample")

        # Query execution analytics
        analytics_res = self.client.get(f"/api/executions/{run_id}/analytics")
        self.assertEqual(analytics_res.status_code, 200)
        self.assertIn("avg_cpu_percent", analytics_res.get_json()["data"])

        # Query system stats
        stats_res = self.client.get("/api/system/stats")
        self.assertEqual(stats_res.status_code, 200)
        self.assertIn("cpu_percent", stats_res.get_json()["data"])

        # Query dashboard summary
        summary_res = self.client.get("/api/dashboard/summary")
        self.assertEqual(summary_res.status_code, 200)
        self.assertEqual(summary_res.get_json()["data"]["total_sandboxes"], 1)

        # Query activity logs
        act_res = self.client.get("/api/activity")
        self.assertEqual(act_res.status_code, 200)
        self.assertGreaterEqual(len(act_res.get_json()["data"]), 1)

    def test_json_error_handling(self):
        self.register("error_tester", "Password123!")
        self.login("error_tester", "Password123!")

        # 404 on nonexistent route
        res = self.client.get("/api/nonexistent_route")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "NOT_FOUND")

        # 404 on nonexistent sandbox
        res = self.client.get("/api/sandboxes/99999")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
