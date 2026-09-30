-- Portable Sandbox Management System - Relational Database Schema
-- SQLite 3.46+ Compatible

PRAGMA foreign_keys = ON;

-- 1. Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Sandboxes Table
CREATE TABLE IF NOT EXISTS sandboxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    working_dir TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, name)
);

-- 3. Execution Runs Table
CREATE TABLE IF NOT EXISTS execution_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sandbox_id INTEGER NOT NULL,
    command TEXT NOT NULL,
    pid INTEGER DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'TERMINATED', 'TIMED_OUT')),
    exit_code INTEGER DEFAULT NULL,
    stdout TEXT DEFAULT '',
    stderr TEXT DEFAULT '',
    start_time DATETIME DEFAULT NULL,
    end_time DATETIME DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sandbox_id) REFERENCES sandboxes(id) ON DELETE CASCADE
);

-- 4. Resource Metrics Table
CREATE TABLE IF NOT EXISTS resource_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cpu_percent REAL NOT NULL CHECK(cpu_percent >= 0.0),
    memory_rss_bytes INTEGER NOT NULL CHECK(memory_rss_bytes >= 0),
    memory_vms_bytes INTEGER NOT NULL DEFAULT 0 CHECK(memory_vms_bytes >= 0),
    thread_count INTEGER NOT NULL DEFAULT 1 CHECK(thread_count >= 0),
    FOREIGN KEY (run_id) REFERENCES execution_runs(id) ON DELETE CASCADE
);

-- 5. Activity Logs Table
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER DEFAULT NULL,
    action TEXT NOT NULL,
    details TEXT DEFAULT '',
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_sandboxes_user_id ON sandboxes(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_sandbox_id ON execution_runs(sandbox_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON execution_runs(status);
CREATE INDEX IF NOT EXISTS idx_metrics_run_time ON resource_metrics(run_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_user_time ON activity_logs(user_id, timestamp);

-- Trigger: Automatically update sandboxes.updated_at on update
CREATE TRIGGER IF NOT EXISTS trg_update_sandboxes_timestamp
AFTER UPDATE ON sandboxes
FOR EACH ROW
BEGIN
    UPDATE sandboxes SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
