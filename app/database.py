"""
Database Layer for Portable Sandbox Management System.
Demonstrates relational database concepts:
- Normalized relational schema (3NF)
- Referential integrity (Foreign Keys with CASCADE and SET NULL)
- Check constraints and unique indices
- Connection-per-operation context management with proper cleanup
- ACID transactions with explicit rollback and commit
- Analytical JOIN and aggregate queries (COUNT, SUM, AVG, MAX)
- Password security via Werkzeug hashing
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from werkzeug.security import check_password_hash, generate_password_hash

# Default paths resolved dynamically for portability
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = str(BASE_DIR / "data" / "sandbox.db")
DEFAULT_SCHEMA_PATH = str(BASE_DIR / "data" / "schema.sql")


@contextmanager
def get_db_connection(db_path: Optional[str] = None):
    """
    Context manager for SQLite database connections.
    Opens a dedicated connection per operation and guarantees closure.
    Enforces foreign key constraints and WAL mode for disk databases.
    """
    target_path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(
        target_path,
        timeout=15.0,
        detect_types=sqlite3.PARSE_DECLTYPES
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        if target_path != ":memory:" and not target_path.startswith("file:"):
            conn.execute("PRAGMA journal_mode = WAL;")
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    """
    Context manager for atomic transaction control.
    Commits on successful block completion or rolls back on exception.
    """
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(db_path: Optional[str] = None, schema_path: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> None:
    """
    Initializes database tables, triggers, and indexes from schema.sql.
    Supports either an existing connection (e.g. :memory:) or opens a connection to db_path.
    """
    target_schema = schema_path or DEFAULT_SCHEMA_PATH
    with open(target_schema, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    if conn is not None:
        conn.executescript(schema_sql)
    else:
        with get_db_connection(db_path) as new_conn:
            new_conn.executescript(schema_sql)


# ==========================================
# 1. USER OPERATIONS
# ==========================================

def create_user(
    username: str,
    password: str,
    role: str = "user",
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> int:
    """Creates a user with Werkzeug-hashed password and returns user id."""
    password_hash = generate_password_hash(password)
    query = """
        INSERT INTO users (username, password_hash, role)
        VALUES (?, ?, ?)
    """

    def _execute(c: sqlite3.Connection, commit: bool) -> int:
        cur = c.cursor()
        cur.execute(query, (username.strip(), password_hash, role))
        if commit:
            c.commit()
        return cur.lastrowid

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


def verify_user(
    username: str,
    password: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """Verifies username and password using check_password_hash. Returns user dict or None."""
    user = get_user_by_username(username, db_path=db_path, conn=conn)
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def get_user_by_id(
    user_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """Fetches a user record by ID."""
    query = "SELECT id, username, password_hash, role, created_at FROM users WHERE id = ?"

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (user_id,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


def get_user_by_username(
    username: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """Fetches a user record by username (case-insensitive)."""
    query = "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?"

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (username.strip(),)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


# ==========================================
# 2. SANDBOX OPERATIONS (CRUD)
# ==========================================

def create_sandbox(
    user_id: int,
    name: str,
    description: str = "",
    working_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> int:
    """Creates a new sandbox workspace record for a user."""
    clean_name = name.strip()
    sb_dir = working_dir or f"sandboxes/sb_{user_id}_{clean_name.lower().replace(' ', '_')}"
    query = """
        INSERT INTO sandboxes (user_id, name, description, working_dir, is_active)
        VALUES (?, ?, ?, ?, 1)
    """

    def _execute(c: sqlite3.Connection, commit: bool) -> int:
        cur = c.cursor()
        cur.execute(query, (user_id, clean_name, description, sb_dir))
        if commit:
            c.commit()
        return cur.lastrowid

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


def get_sandbox_by_id(
    sandbox_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """Fetches a sandbox by its primary key ID."""
    query = """
        SELECT id, user_id, name, description, working_dir, is_active, created_at, updated_at
        FROM sandboxes WHERE id = ?
    """

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (sandbox_id,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


def list_sandboxes_for_user(
    user_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Lists all sandboxes owned by a specific user."""
    query = """
        SELECT id, user_id, name, description, working_dir, is_active, created_at, updated_at
        FROM sandboxes WHERE user_id = ? ORDER BY created_at DESC
    """

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, (user_id,)).fetchall()
        return [dict(r) for r in rows]

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


def update_sandbox(
    sandbox_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[int] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> bool:
    """Updates sandbox attributes. Triggers automatic updated_at timestamp update."""
    fields = []
    params = []
    if name is not None:
        fields.append("name = ?")
        params.append(name.strip())
    if description is not None:
        fields.append("description = ?")
        params.append(description)
    if is_active is not None:
        fields.append("is_active = ?")
        params.append(is_active)

    if not fields:
        return False

    params.append(sandbox_id)
    query = f"UPDATE sandboxes SET {', '.join(fields)} WHERE id = ?"

    def _execute(c: sqlite3.Connection, commit: bool) -> bool:
        cur = c.cursor()
        cur.execute(query, tuple(params))
        if commit:
            c.commit()
        return cur.rowcount > 0

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


def delete_sandbox(
    sandbox_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> bool:
    """Deletes a sandbox. Foreign key ON DELETE CASCADE automatically removes runs and metrics."""
    query = "DELETE FROM sandboxes WHERE id = ?"

    def _execute(c: sqlite3.Connection, commit: bool) -> bool:
        cur = c.cursor()
        cur.execute(query, (sandbox_id,))
        if commit:
            c.commit()
        return cur.rowcount > 0

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


# ==========================================
# 3. EXECUTION RUNS OPERATIONS
# ==========================================

def create_execution_run(
    sandbox_id: int,
    command: str,
    status: str = "QUEUED",
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> int:
    """Records a new execution run attached to a sandbox."""
    query = """
        INSERT INTO execution_runs (sandbox_id, command, status)
        VALUES (?, ?, ?)
    """

    def _execute(c: sqlite3.Connection, commit: bool) -> int:
        cur = c.cursor()
        cur.execute(query, (sandbox_id, command, status))
        if commit:
            c.commit()
        return cur.lastrowid

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


def update_execution_run(
    run_id: int,
    status: Optional[str] = None,
    pid: Optional[int] = None,
    exit_code: Optional[int] = None,
    stdout: Optional[str] = None,
    stderr: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> bool:
    """Updates execution run state, PID, exit code, outputs, and timestamps."""
    fields = []
    params = []
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if pid is not None:
        fields.append("pid = ?")
        params.append(pid)
    if exit_code is not None:
        fields.append("exit_code = ?")
        params.append(exit_code)
    if stdout is not None:
        fields.append("stdout = ?")
        params.append(stdout)
    if stderr is not None:
        fields.append("stderr = ?")
        params.append(stderr)
    if start_time is not None:
        fields.append("start_time = ?")
        params.append(start_time)
    if end_time is not None:
        fields.append("end_time = ?")
        params.append(end_time)

    if not fields:
        return False

    params.append(run_id)
    query = f"UPDATE execution_runs SET {', '.join(fields)} WHERE id = ?"

    def _execute(c: sqlite3.Connection, commit: bool) -> bool:
        cur = c.cursor()
        cur.execute(query, tuple(params))
        if commit:
            c.commit()
        return cur.rowcount > 0

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


def get_execution_run_by_id(
    run_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """Fetches a single execution run by its ID."""
    query = """
        SELECT id, sandbox_id, command, pid, status, exit_code, stdout, stderr,
               start_time, end_time, created_at
        FROM execution_runs WHERE id = ?
    """

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (run_id,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


def list_execution_runs_for_sandbox(
    sandbox_id: int,
    limit: int = 50,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Lists execution runs for a sandbox, sorted by most recent first."""
    query = """
        SELECT id, sandbox_id, command, pid, status, exit_code, stdout, stderr,
               start_time, end_time, created_at
        FROM execution_runs WHERE sandbox_id = ?
        ORDER BY created_at DESC LIMIT ?
    """

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, (sandbox_id, limit)).fetchall()
        return [dict(r) for r in rows]

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


# ==========================================
# 4. RESOURCE METRICS OPERATIONS
# ==========================================

def log_resource_metric(
    run_id: int,
    cpu_percent: float,
    memory_rss_bytes: int,
    memory_vms_bytes: int = 0,
    thread_count: int = 1,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> int:
    """Logs an individual resource utilization metric sample."""
    query = """
        INSERT INTO resource_metrics (run_id, cpu_percent, memory_rss_bytes, memory_vms_bytes, thread_count)
        VALUES (?, ?, ?, ?, ?)
    """

    def _execute(c: sqlite3.Connection, commit: bool) -> int:
        cur = c.cursor()
        cur.execute(query, (run_id, cpu_percent, memory_rss_bytes, memory_vms_bytes, thread_count))
        if commit:
            c.commit()
        return cur.lastrowid

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


def get_metrics_for_run(
    run_id: int,
    limit: int = 100,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Retrieves chronological metrics recorded for an execution run."""
    query = """
        SELECT id, run_id, timestamp, cpu_percent, memory_rss_bytes, memory_vms_bytes, thread_count
        FROM resource_metrics WHERE run_id = ?
        ORDER BY timestamp ASC LIMIT ?
    """

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, (run_id, limit)).fetchall()
        return [dict(r) for r in rows]

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


# ==========================================
# 5. ACTIVITY LOG OPERATIONS
# ==========================================

def log_activity(
    action: str,
    user_id: Optional[int] = None,
    details: str = "",
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> int:
    """Records an action into the audit trail."""
    query = """
        INSERT INTO activity_logs (user_id, action, details)
        VALUES (?, ?, ?)
    """

    def _execute(c: sqlite3.Connection, commit: bool) -> int:
        cur = c.cursor()
        cur.execute(query, (user_id, action, details))
        if commit:
            c.commit()
        return cur.lastrowid

    if conn is not None:
        return _execute(conn, commit=False)
    with get_db_connection(db_path) as c:
        return _execute(c, commit=True)


def list_recent_activity(
    user_id: Optional[int] = None,
    limit: int = 20,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Lists recent activity logs, optionally filtered by user_id."""
    if user_id is not None:
        query = """
            SELECT id, user_id, action, details, timestamp
            FROM activity_logs WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """
        params = (user_id, limit)
    else:
        query = """
            SELECT id, user_id, action, details, timestamp
            FROM activity_logs ORDER BY timestamp DESC LIMIT ?
        """
        params = (limit,)

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


# ==========================================
# 6. ANALYTICAL JOIN & AGGREGATE QUERIES (DBMS DEMO)
# ==========================================

def get_user_dashboard_summary(
    user_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Demonstrates multi-table LEFT JOIN and conditional aggregation.
    Aggregates:
    - Total sandboxes owned
    - Total execution runs triggered
    - Active runs ('RUNNING')
    - Successful runs ('COMPLETED')
    - Failed/Terminated runs ('FAILED', 'TERMINATED', 'TIMED_OUT')
    """
    query = """
        SELECT
            u.id AS user_id,
            u.username,
            COUNT(DISTINCT s.id) AS total_sandboxes,
            COUNT(DISTINCT r.id) AS total_runs,
            COALESCE(SUM(CASE WHEN r.status = 'RUNNING' THEN 1 ELSE 0 END), 0) AS active_runs,
            COALESCE(SUM(CASE WHEN r.status = 'COMPLETED' THEN 1 ELSE 0 END), 0) AS completed_runs,
            COALESCE(SUM(CASE WHEN r.status IN ('FAILED', 'TERMINATED', 'TIMED_OUT') THEN 1 ELSE 0 END), 0) AS failed_runs
        FROM users u
        LEFT JOIN sandboxes s ON u.id = s.user_id
        LEFT JOIN execution_runs r ON s.id = r.sandbox_id
        WHERE u.id = ?
        GROUP BY u.id, u.username;
    """

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (user_id,)).fetchone()
        if row:
            return dict(row)
        return {
            "user_id": user_id,
            "username": "",
            "total_sandboxes": 0,
            "total_runs": 0,
            "active_runs": 0,
            "completed_runs": 0,
            "failed_runs": 0
        }

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


def get_run_resource_analytics(
    run_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Demonstrates analytical aggregation (AVG, MAX, COUNT) with LEFT JOIN.
    Computes statistical metrics (avg CPU %, peak CPU %, avg RAM MB, peak RAM MB).
    """
    query = """
        SELECT
            r.id AS run_id,
            r.command,
            r.status,
            COUNT(m.id) AS sample_count,
            ROUND(COALESCE(AVG(m.cpu_percent), 0.0), 2) AS avg_cpu_percent,
            ROUND(COALESCE(MAX(m.cpu_percent), 0.0), 2) AS peak_cpu_percent,
            ROUND(COALESCE(AVG(m.memory_rss_bytes), 0) / (1024.0 * 1024.0), 2) AS avg_rss_mb,
            ROUND(COALESCE(MAX(m.memory_rss_bytes), 0) / (1024.0 * 1024.0), 2) AS peak_rss_mb,
            COALESCE(MAX(m.thread_count), 0) AS peak_threads
        FROM execution_runs r
        LEFT JOIN resource_metrics m ON r.id = m.run_id
        WHERE r.id = ?
        GROUP BY r.id;
    """

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (run_id,)).fetchone()
        return dict(row) if row else {}

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)


def get_sandbox_analytics(
    sandbox_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Demonstrates JOIN and aggregate analytics for a single sandbox workspace.
    """
    query = """
        SELECT
            s.id AS sandbox_id,
            s.name AS sandbox_name,
            COUNT(r.id) AS total_runs,
            COALESCE(SUM(CASE WHEN r.status = 'COMPLETED' THEN 1 ELSE 0 END), 0) AS successful_runs,
            COALESCE(SUM(CASE WHEN r.status IN ('FAILED', 'TERMINATED', 'TIMED_OUT') THEN 1 ELSE 0 END), 0) AS failed_runs
        FROM sandboxes s
        LEFT JOIN execution_runs r ON s.id = r.sandbox_id
        WHERE s.id = ?
        GROUP BY s.id, s.name;
    """

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (sandbox_id,)).fetchone()
        return dict(row) if row else {}

    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)
