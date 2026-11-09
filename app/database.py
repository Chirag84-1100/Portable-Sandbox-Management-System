import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from werkzeug.security import check_password_hash, generate_password_hash
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_ROOT = Path(
    os.environ.get("SANDBOX_DATA_ROOT", str(BASE_DIR))
).expanduser().resolve()
DEFAULT_DB_PATH = str(STORAGE_ROOT / "data" / "sandbox.db")
DEFAULT_SCHEMA_PATH = str(BASE_DIR / "data" / "schema.sql")

@contextmanager
def get_db_connection(db_path: Optional[str]=None):
    target_path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(target_path, timeout=15.0, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys = ON;')
        if target_path != ':memory:' and (not target_path.startswith('file:')):
            if os.environ.get("SANDBOX_DATA_ROOT"):
                from app.storage import validate_portable_storage
                validate_portable_storage()
                conn.execute('PRAGMA journal_mode = DELETE;')
                conn.execute('PRAGMA synchronous = FULL;')
            else:
                conn.execute('PRAGMA journal_mode = WAL;')
        yield conn
    finally:
        conn.close()

@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def init_db(db_path: Optional[str]=None, schema_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> None:
    target_schema = schema_path or DEFAULT_SCHEMA_PATH
    with open(target_schema, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    if conn is not None:
        conn.executescript(schema_sql)
    else:
        with get_db_connection(db_path) as new_conn:
            new_conn.executescript(schema_sql)

def create_user(username: str, password: str, role: str='user', db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> int:
    password_hash = generate_password_hash(password)
    query = '\n\n        INSERT INTO users (username, password_hash, role)\n\n        VALUES (?, ?, ?)\n\n    '

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

def verify_user(username: str, password: str, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Optional[Dict[str, Any]]:
    user = get_user_by_username(username, db_path=db_path, conn=conn)
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def get_user_by_id(user_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Optional[Dict[str, Any]]:
    query = 'SELECT id, username, password_hash, role, created_at FROM users WHERE id = ?'

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (user_id,)).fetchone()
        return dict(row) if row else None
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def get_user_by_username(username: str, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Optional[Dict[str, Any]]:
    query = 'SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?'

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (username.strip(),)).fetchone()
        return dict(row) if row else None
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def create_sandbox(user_id: int, name: str, description: str='', working_dir: Optional[str]=None, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> int:
    clean_name = name.strip()
    sb_dir = working_dir or f"sandboxes/sb_{user_id}_{clean_name.lower().replace(' ', '_')}"
    query = '\n\n        INSERT INTO sandboxes (user_id, name, description, working_dir, is_active)\n\n        VALUES (?, ?, ?, ?, 1)\n\n    '

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

def get_sandbox_by_id(sandbox_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Optional[Dict[str, Any]]:
    query = '\n\n        SELECT id, user_id, name, description, working_dir, is_active, created_at, updated_at\n\n        FROM sandboxes WHERE id = ?\n\n    '

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (sandbox_id,)).fetchone()
        return dict(row) if row else None
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def list_sandboxes_for_user(user_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> List[Dict[str, Any]]:
    query = '\n\n        SELECT id, user_id, name, description, working_dir, is_active, created_at, updated_at\n\n        FROM sandboxes WHERE user_id = ? ORDER BY created_at DESC\n\n    '

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, (user_id,)).fetchall()
        return [dict(r) for r in rows]
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def update_sandbox(sandbox_id: int, name: Optional[str]=None, description: Optional[str]=None, is_active: Optional[int]=None, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> bool:
    fields = []
    params = []
    if name is not None:
        fields.append('name = ?')
        params.append(name.strip())
    if description is not None:
        fields.append('description = ?')
        params.append(description)
    if is_active is not None:
        fields.append('is_active = ?')
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

def delete_sandbox(sandbox_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> bool:
    query = 'DELETE FROM sandboxes WHERE id = ?'

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

def create_execution_run(sandbox_id: int, command: str, status: str='QUEUED', db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> int:
    query = '\n\n        INSERT INTO execution_runs (sandbox_id, command, status)\n\n        VALUES (?, ?, ?)\n\n    '

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

def update_execution_run(run_id: int, status: Optional[str]=None, pid: Optional[int]=None, exit_code: Optional[int]=None, stdout: Optional[str]=None, stderr: Optional[str]=None, start_time: Optional[str]=None, end_time: Optional[str]=None, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> bool:
    fields = []
    params = []
    if status is not None:
        fields.append('status = ?')
        params.append(status)
    if pid is not None:
        fields.append('pid = ?')
        params.append(pid)
    if exit_code is not None:
        fields.append('exit_code = ?')
        params.append(exit_code)
    if stdout is not None:
        fields.append('stdout = ?')
        params.append(stdout)
    if stderr is not None:
        fields.append('stderr = ?')
        params.append(stderr)
    if start_time is not None:
        fields.append('start_time = ?')
        params.append(start_time)
    if end_time is not None:
        fields.append('end_time = ?')
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

def get_execution_run_by_id(run_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Optional[Dict[str, Any]]:
    query = '\n\n        SELECT id, sandbox_id, command, pid, status, exit_code, stdout, stderr,\n\n               start_time, end_time, created_at\n\n        FROM execution_runs WHERE id = ?\n\n    '

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (run_id,)).fetchone()
        return dict(row) if row else None
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def list_execution_runs_for_sandbox(sandbox_id: int, limit: int=50, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> List[Dict[str, Any]]:
    query = '\n\n        SELECT id, sandbox_id, command, pid, status, exit_code, stdout, stderr,\n\n               start_time, end_time, created_at\n\n        FROM execution_runs WHERE sandbox_id = ?\n\n        ORDER BY created_at DESC LIMIT ?\n\n    '

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, (sandbox_id, limit)).fetchall()
        return [dict(r) for r in rows]
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def log_resource_metric(run_id: int, cpu_percent: float, memory_rss_bytes: int, memory_vms_bytes: int=0, thread_count: int=1, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> int:
    query = '\n\n        INSERT INTO resource_metrics (run_id, cpu_percent, memory_rss_bytes, memory_vms_bytes, thread_count)\n\n        VALUES (?, ?, ?, ?, ?)\n\n    '

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

def get_metrics_for_run(run_id: int, limit: int=100, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> List[Dict[str, Any]]:
    query = '\n\n        SELECT id, run_id, timestamp, cpu_percent, memory_rss_bytes, memory_vms_bytes, thread_count\n\n        FROM resource_metrics WHERE run_id = ?\n\n        ORDER BY timestamp ASC LIMIT ?\n\n    '

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, (run_id, limit)).fetchall()
        return [dict(r) for r in rows]
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def log_activity(action: str, user_id: Optional[int]=None, details: str='', db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> int:
    query = '\n\n        INSERT INTO activity_logs (user_id, action, details)\n\n        VALUES (?, ?, ?)\n\n    '

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

def list_recent_activity(user_id: Optional[int]=None, limit: int=20, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> List[Dict[str, Any]]:
    if user_id is not None:
        query = '\n\n            SELECT id, user_id, action, details, timestamp\n\n            FROM activity_logs WHERE user_id = ?\n\n            ORDER BY timestamp DESC LIMIT ?\n\n        '
        params = (user_id, limit)
    else:
        query = '\n\n            SELECT id, user_id, action, details, timestamp\n\n            FROM activity_logs ORDER BY timestamp DESC LIMIT ?\n\n        '
        params = (limit,)

    def _execute(c: sqlite3.Connection):
        rows = c.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def get_user_dashboard_summary(user_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Dict[str, Any]:
    query = "\n\n        SELECT\n\n            u.id AS user_id,\n\n            u.username,\n\n            COUNT(DISTINCT s.id) AS total_sandboxes,\n\n            COUNT(DISTINCT r.id) AS total_runs,\n\n            COALESCE(SUM(CASE WHEN r.status = 'RUNNING' THEN 1 ELSE 0 END), 0) AS active_runs,\n\n            COALESCE(SUM(CASE WHEN r.status = 'COMPLETED' THEN 1 ELSE 0 END), 0) AS completed_runs,\n\n            COALESCE(SUM(CASE WHEN r.status IN ('FAILED', 'TERMINATED', 'TIMED_OUT') THEN 1 ELSE 0 END), 0) AS failed_runs\n\n        FROM users u\n\n        LEFT JOIN sandboxes s ON u.id = s.user_id\n\n        LEFT JOIN execution_runs r ON s.id = r.sandbox_id\n\n        WHERE u.id = ?\n\n        GROUP BY u.id, u.username;\n\n    "

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (user_id,)).fetchone()
        if row:
            return dict(row)
        return {'user_id': user_id, 'username': '', 'total_sandboxes': 0, 'total_runs': 0, 'active_runs': 0, 'completed_runs': 0, 'failed_runs': 0}
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def get_run_resource_analytics(run_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Dict[str, Any]:
    query = '\n\n        SELECT\n\n            r.id AS run_id,\n\n            r.command,\n\n            r.status,\n\n            COUNT(m.id) AS sample_count,\n\n            ROUND(COALESCE(AVG(m.cpu_percent), 0.0), 2) AS avg_cpu_percent,\n\n            ROUND(COALESCE(MAX(m.cpu_percent), 0.0), 2) AS peak_cpu_percent,\n\n            ROUND(COALESCE(AVG(m.memory_rss_bytes), 0) / (1024.0 * 1024.0), 2) AS avg_rss_mb,\n\n            ROUND(COALESCE(MAX(m.memory_rss_bytes), 0) / (1024.0 * 1024.0), 2) AS peak_rss_mb,\n\n            COALESCE(MAX(m.thread_count), 0) AS peak_threads\n\n        FROM execution_runs r\n\n        LEFT JOIN resource_metrics m ON r.id = m.run_id\n\n        WHERE r.id = ?\n\n        GROUP BY r.id;\n\n    '

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (run_id,)).fetchone()
        return dict(row) if row else {}
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)

def get_sandbox_analytics(sandbox_id: int, db_path: Optional[str]=None, conn: Optional[sqlite3.Connection]=None) -> Dict[str, Any]:
    query = "\n\n        SELECT\n\n            s.id AS sandbox_id,\n\n            s.name AS sandbox_name,\n\n            COUNT(r.id) AS total_runs,\n\n            COALESCE(SUM(CASE WHEN r.status = 'COMPLETED' THEN 1 ELSE 0 END), 0) AS successful_runs,\n\n            COALESCE(SUM(CASE WHEN r.status IN ('FAILED', 'TERMINATED', 'TIMED_OUT') THEN 1 ELSE 0 END), 0) AS failed_runs\n\n        FROM sandboxes s\n\n        LEFT JOIN execution_runs r ON s.id = r.sandbox_id\n\n        WHERE s.id = ?\n\n        GROUP BY s.id, s.name;\n\n    "

    def _execute(c: sqlite3.Connection):
        row = c.execute(query, (sandbox_id,)).fetchone()
        return dict(row) if row else {}
    if conn is not None:
        return _execute(conn)
    with get_db_connection(db_path) as c:
        return _execute(c)
