"""
Unit and Integration Tests for Database Layer (app/database.py).
Runs strictly against in-memory SQLite (:memory:) to preserve clean disk environment.
Tests DBMS principles:
1. Schema & PRAGMA configuration (Foreign Keys = ON)
2. User Authentication & Werkzeug Hashing
3. Domain Integrity (CHECK constraints)
4. Entity Integrity (PRIMARY KEY & UNIQUE constraints)
5. Referential Integrity (FOREIGN KEY CASCADE)
6. Transaction Atomicity & Rollback
7. Database Triggers (Automatic timestamp update)
8. Analytical JOIN & Aggregate Queries
"""

import os
import sqlite3
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import (
    init_db,
    transaction,
    create_user,
    verify_user,
    get_user_by_id,
    get_user_by_username,
    create_sandbox,
    get_sandbox_by_id,
    list_sandboxes_for_user,
    update_sandbox,
    delete_sandbox,
    create_execution_run,
    update_execution_run,
    get_execution_run_by_id,
    list_execution_runs_for_sandbox,
    log_resource_metric,
    get_metrics_for_run,
    log_activity,
    list_recent_activity,
    get_user_dashboard_summary,
    get_run_resource_analytics,
    get_sandbox_analytics,
)


class TestDatabaseLayer(unittest.TestCase):
    def setUp(self):
        """Create fresh in-memory database connection and initialize schema."""
        self.conn = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        init_db(conn=self.conn)

    def tearDown(self):
        """Close in-memory database connection."""
        self.conn.close()

    # ----------------------------------------------------
    # 1. Schema & PRAGMA Tests
    # ----------------------------------------------------
    def test_schema_and_pragmas(self):
        cursor = self.conn.execute("PRAGMA foreign_keys;")
        fk_status = cursor.fetchone()[0]
        self.assertEqual(fk_status, 1, "Foreign keys must be enabled (PRAGMA foreign_keys = 1)")

        tables = [
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        ]
        expected_tables = {"users", "sandboxes", "execution_runs", "resource_metrics", "activity_logs"}
        for t in expected_tables:
            self.assertIn(t, tables, f"Expected table '{t}' was not created by schema.sql")

    # ----------------------------------------------------
    # 2. User & Werkzeug Authentication Tests
    # ----------------------------------------------------
    def test_user_creation_and_auth(self):
        user_id = create_user("Alice", "SuperSecret123!", role="user", conn=self.conn)
        self.assertIsInstance(user_id, int)
        self.assertGreater(user_id, 0)

        user = get_user_by_id(user_id, conn=self.conn)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "Alice")
        self.assertNotEqual(user["password_hash"], "SuperSecret123!", "Password must be securely hashed")

        # Test verification
        valid_user = verify_user("alice", "SuperSecret123!", conn=self.conn)
        self.assertIsNotNone(valid_user, "Case-insensitive username match should succeed with correct password")
        self.assertEqual(valid_user["id"], user_id)

        invalid_user = verify_user("Alice", "WrongPassword", conn=self.conn)
        self.assertIsNone(invalid_user, "Verification must fail on incorrect password")

        nonexistent_user = verify_user("Bob", "SuperSecret123!", conn=self.conn)
        self.assertIsNone(nonexistent_user, "Verification must fail on non-existent username")

    # ----------------------------------------------------
    # 3. Entity Integrity: UNIQUE Constraints
    # ----------------------------------------------------
    def test_unique_constraints(self):
        create_user("Bob", "password123", conn=self.conn)
        with self.assertRaises(sqlite3.IntegrityError):
            # Attempt to create duplicate username (case-insensitive)
            create_user("bob", "anotherpassword", conn=self.conn)

        user_id = get_user_by_username("Bob", conn=self.conn)["id"]
        create_sandbox(user_id, "Project Alpha", conn=self.conn)

        with self.assertRaises(sqlite3.IntegrityError):
            # Same user cannot have two sandboxes with the same name
            create_sandbox(user_id, "Project Alpha", conn=self.conn)

        # Different user CAN have a sandbox with the same name
        user2_id = create_user("Charlie", "password456", conn=self.conn)
        sb2_id = create_sandbox(user2_id, "Project Alpha", conn=self.conn)
        self.assertGreater(sb2_id, 0)

    # ----------------------------------------------------
    # 4. Domain Integrity: CHECK Constraints
    # ----------------------------------------------------
    def test_check_constraints(self):
        # Invalid role
        with self.assertRaises(sqlite3.IntegrityError):
            create_user("Dave", "pass", role="superuser", conn=self.conn)

        user_id = create_user("Dave", "pass", role="user", conn=self.conn)
        sb_id = create_sandbox(user_id, "Test Sandbox", conn=self.conn)

        # Invalid execution status
        with self.assertRaises(sqlite3.IntegrityError):
            create_execution_run(sb_id, "ls", status="INVALID_STATUS", conn=self.conn)

        run_id = create_execution_run(sb_id, "ls", status="QUEUED", conn=self.conn)

        # Negative CPU percent
        with self.assertRaises(sqlite3.IntegrityError):
            log_resource_metric(run_id, cpu_percent=-5.0, memory_rss_bytes=1000, conn=self.conn)

        # Negative memory RSS bytes
        with self.assertRaises(sqlite3.IntegrityError):
            log_resource_metric(run_id, cpu_percent=10.0, memory_rss_bytes=-100, conn=self.conn)

    # ----------------------------------------------------
    # 5. Referential Integrity: Foreign Key CASCADE
    # ----------------------------------------------------
    def test_foreign_key_cascade(self):
        user_id = create_user("Eve", "pass123", conn=self.conn)
        sb_id = create_sandbox(user_id, "Sandbox To Delete", conn=self.conn)
        run_id = create_execution_run(sb_id, "echo 1", status="COMPLETED", conn=self.conn)
        log_resource_metric(run_id, cpu_percent=12.5, memory_rss_bytes=1048576, conn=self.conn)

        # Assert records exist
        self.assertIsNotNone(get_sandbox_by_id(sb_id, conn=self.conn))
        self.assertIsNotNone(get_execution_run_by_id(run_id, conn=self.conn))
        self.assertEqual(len(get_metrics_for_run(run_id, conn=self.conn)), 1)

        # Delete Sandbox -> Cascade to Run and Metrics
        delete_sandbox(sb_id, conn=self.conn)
        self.assertIsNone(get_sandbox_by_id(sb_id, conn=self.conn))
        self.assertIsNone(get_execution_run_by_id(run_id, conn=self.conn), "Execution run should be cascaded on sandbox delete")
        self.assertEqual(len(get_metrics_for_run(run_id, conn=self.conn)), 0, "Metrics should be cascaded on run delete")

        # Test activity log SET NULL on user deletion
        log_id = log_activity("LOGIN", user_id=user_id, details="User logged in", conn=self.conn)
        self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()

        log_row = self.conn.execute("SELECT user_id FROM activity_logs WHERE id = ?", (log_id,)).fetchone()
        self.assertIsNone(log_row["user_id"], "Activity log user_id must be SET NULL when user is deleted")

    # ----------------------------------------------------
    # 6. ACID Transactions & Rollback
    # ----------------------------------------------------
    def test_transaction_rollback(self):
        user_id = create_user("Frank", "pass", conn=self.conn)
        sb_id = create_sandbox(user_id, "Tx Sandbox", conn=self.conn)

        try:
            with transaction(self.conn):
                create_execution_run(sb_id, "cmd 1", status="QUEUED", conn=self.conn)
                # Intentionally trigger an error
                raise ValueError("Forced error to test rollback")
        except ValueError:
            pass

        runs = list_execution_runs_for_sandbox(sb_id, conn=self.conn)
        self.assertEqual(len(runs), 0, "Transaction rollback must leave database unmodified after failure")

    # ----------------------------------------------------
    # 7. Database Trigger: Updated At
    # ----------------------------------------------------
    def test_trigger_update_timestamp(self):
        user_id = create_user("Grace", "pass", conn=self.conn)
        sb_id = create_sandbox(user_id, "Trigger SB", description="Initial", conn=self.conn)
        sb_before = get_sandbox_by_id(sb_id, conn=self.conn)

        # Update sandbox description
        update_sandbox(sb_id, description="Updated Description", conn=self.conn)
        sb_after = get_sandbox_by_id(sb_id, conn=self.conn)

        self.assertEqual(sb_after["description"], "Updated Description")
        self.assertIsNotNone(sb_after["updated_at"])

    # ----------------------------------------------------
    # 8. Analytical JOIN & Aggregate Queries
    # ----------------------------------------------------
    def test_analytical_join_and_aggregates(self):
        user_id = create_user("Analyst", "pass123", conn=self.conn)
        sb1 = create_sandbox(user_id, "SB 1", conn=self.conn)
        sb2 = create_sandbox(user_id, "SB 2", conn=self.conn)

        run1 = create_execution_run(sb1, "python task1.py", status="RUNNING", conn=self.conn)
        run2 = create_execution_run(sb1, "python task2.py", status="COMPLETED", conn=self.conn)
        run3 = create_execution_run(sb2, "python task3.py", status="FAILED", conn=self.conn)

        # Add metrics for run2 (50 MB and 100 MB RSS, CPU 20% and 40%)
        log_resource_metric(run2, cpu_percent=20.0, memory_rss_bytes=52428800, thread_count=2, conn=self.conn)
        log_resource_metric(run2, cpu_percent=40.0, memory_rss_bytes=104857600, thread_count=4, conn=self.conn)

        # 1. User Dashboard Summary (LEFT JOIN + conditional aggregation)
        summary = get_user_dashboard_summary(user_id, conn=self.conn)
        self.assertEqual(summary["total_sandboxes"], 2)
        self.assertEqual(summary["total_runs"], 3)
        self.assertEqual(summary["active_runs"], 1)
        self.assertEqual(summary["completed_runs"], 1)
        self.assertEqual(summary["failed_runs"], 1)

        # 2. Run Resource Analytics (INNER/LEFT JOIN + AVG/MAX aggregation)
        analytics = get_run_resource_analytics(run2, conn=self.conn)
        self.assertEqual(analytics["sample_count"], 2)
        self.assertEqual(analytics["avg_cpu_percent"], 30.0)
        self.assertEqual(analytics["peak_cpu_percent"], 40.0)
        self.assertAlmostEqual(analytics["avg_rss_mb"], 75.0, places=1)
        self.assertAlmostEqual(analytics["peak_rss_mb"], 100.0, places=1)
        self.assertEqual(analytics["peak_threads"], 4)

        # 3. Sandbox Analytics
        sb_stats = get_sandbox_analytics(sb1, conn=self.conn)
        self.assertEqual(sb_stats["total_runs"], 2)
        self.assertEqual(sb_stats["successful_runs"], 1)
        self.assertEqual(sb_stats["failed_runs"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
