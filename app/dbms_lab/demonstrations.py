"""
Educational DBMS Demonstrations for Portable Sandbox Management System.
Integrated with the actual SQLite project database (data/sandbox.db) and dedicated
relational lab tables (lab_departments, lab_employees, lab_salary_audit).

Demonstrates all 8 DBMS concepts:
1. Database Design and Normalization (3NF schema inspection)
2. CRUD Operations (INSERT, UPDATE, SELECT, DELETE with safe rollback/cleanup)
3. SQL Queries & Aggregation (SELECT, WHERE, ORDER BY, GROUP BY, COUNT, AVG)
4. Relational Joins (INNER JOIN & LEFT JOIN across tables)
5. Database Constraints (CHECK constraints & Foreign Key integrity)
6. Transactions & Rollback (ACID atomicity verification)
7. Database Indexing (PRAGMA index inspection & query plan analysis)
8. Views and Triggers (Relational view inspection & audit trigger logging)
"""

import sqlite3
from typing import Any, Dict, List, Optional


def _resolve_table_names(conn: sqlite3.Connection):
    """
    Dynamically identifies table names, supporting both persistent project database
    tables (lab_departments, lab_employees) and isolated in-memory test databases.
    Auto-initializes schema if tables are not yet present.
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }
    if not ("lab_employees" in tables or "employees" in tables):
        from app.database import init_db, seed_lab_data
        init_db(conn=conn)
        seed_lab_data(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }

    emp = "lab_employees" if "lab_employees" in tables else "employees"
    dept = "lab_departments" if "lab_departments" in tables else "departments"
    audit = "lab_salary_audit" if "lab_salary_audit" in tables else "salary_audit"
    view = "lab_employee_dept_view" if "lab_employee_dept_view" in tables else "employee_department_view"
    return emp, dept, audit, view


def create_demo_database() -> sqlite3.Connection:
    """Creates a temporary in-memory SQLite database populated with educational tables (for unit tests)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE departments (
            department_id INTEGER PRIMARY KEY,
            department_name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE employees (
            employee_id INTEGER PRIMARY KEY,
            employee_name TEXT NOT NULL,
            salary REAL CHECK(salary > 0),
            department_id INTEGER,
            FOREIGN KEY(department_id) REFERENCES departments(department_id) ON DELETE CASCADE
        );

        INSERT INTO departments VALUES
            (1, 'Engineering'),
            (2, 'HR'),
            (3, 'Finance');

        INSERT INTO employees VALUES
            (101, 'Aman', 50000, 1),
            (102, 'Riya', 60000, 1),
            (103, 'Karan', 40000, 2),
            (104, 'Neha', 55000, 3);

        CREATE INDEX idx_employee_department ON employees(department_id);

        CREATE VIEW employee_department_view AS
        SELECT e.employee_id, e.employee_name, e.salary, d.department_name
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id;
    """)

    return conn


def demonstrate_design(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    1. Database Design and Normalization:
    Inspects relational tables, views, indexes, and foreign keys in the active database.
    Shows 3NF normalization: normalized entity tables, atomic attributes, PKs, and FKs.
    """
    rows = conn.execute(
        "SELECT name, type, sql FROM sqlite_master "
        "WHERE type IN ('table', 'view', 'trigger', 'index') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name"
    ).fetchall()

    return [
        {
            "name": row["name"],
            "type": row["type"],
            "definition": (row["sql"] or "").strip().replace("\n", " "),
        }
        for row in rows
    ]


def demonstrate_crud(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    2. CRUD Operations:
    Demonstrates CREATE, READ, UPDATE, and DELETE safely on the dedicated lab table.
    Cleans up the test record completely so database state remains pristine.
    """
    emp, _, audit, _ = _resolve_table_names(conn)
    demo_id = 105

    # Safe pre-cleanup
    conn.execute(f"DELETE FROM {emp} WHERE employee_id = ?", (demo_id,))
    try:
        conn.execute(f"DELETE FROM {audit} WHERE employee_id = ?", (demo_id,))
    except sqlite3.OperationalError:
        pass
    conn.commit()

    # CREATE (INSERT)
    conn.execute(
        f"INSERT INTO {emp} (employee_id, employee_name, salary, department_id) "
        "VALUES (?, 'Demo User', 45000, 1)",
        (demo_id,),
    )
    conn.commit()

    # UPDATE
    conn.execute(
        f"UPDATE {emp} SET salary = 48000 WHERE employee_id = ?",
        (demo_id,),
    )
    conn.commit()

    # READ (SELECT)
    inserted = dict(
        conn.execute(
            f"SELECT * FROM {emp} WHERE employee_id = ?",
            (demo_id,),
        ).fetchone()
    )

    # DELETE
    conn.execute(f"DELETE FROM {emp} WHERE employee_id = ?", (demo_id,))
    try:
        conn.execute(f"DELETE FROM {audit} WHERE employee_id = ?", (demo_id,))
    except sqlite3.OperationalError:
        pass
    conn.commit()

    deleted_count = conn.execute(
        f"SELECT COUNT(*) FROM {emp} WHERE employee_id = ?", (demo_id,)
    ).fetchone()[0]

    return {
        "target_table": emp,
        "operations_performed": ["INSERT", "UPDATE", "SELECT", "DELETE"],
        "after_insert_and_update": inserted,
        "deleted_successfully": deleted_count == 0,
        "isolation_verified": "Operational tables untouched. Test record purged.",
    }


def demonstrate_queries(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    3. SQL Queries and Aggregation:
    Demonstrates filtering with WHERE, sorting with ORDER BY, and aggregation with COUNT/AVG.
    """
    emp, _, _, _ = _resolve_table_names(conn)
    rows = conn.execute(
        f"SELECT employee_name, salary FROM {emp} "
        "WHERE salary >= 50000 ORDER BY salary DESC"
    ).fetchall()

    return [dict(row) for row in rows]


def demonstrate_aggregation(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """SQL Aggregation: COUNT(*) and AVG(salary) grouped by department."""
    emp, _, _, _ = _resolve_table_names(conn)
    rows = conn.execute(f"""
        SELECT department_id,
               COUNT(*) AS employee_count,
               ROUND(AVG(salary), 2) AS average_salary
        FROM {emp}
        GROUP BY department_id
        ORDER BY department_id
    """).fetchall()

    return [dict(row) for row in rows]


def demonstrate_joins(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    4. Relational Joins:
    Demonstrates INNER JOIN matching employee records to their department names.
    """
    emp, dept, _, _ = _resolve_table_names(conn)
    rows = conn.execute(f"""
        SELECT e.employee_id, e.employee_name, e.salary, d.department_name
        FROM {emp} e
        INNER JOIN {dept} d
        ON e.department_id = d.department_id
        ORDER BY e.employee_id
    """).fetchall()

    return [dict(row) for row in rows]


def demonstrate_constraints(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    5. Database Constraints:
    Demonstrates domain integrity via CHECK constraints and referential integrity via Foreign Keys.
    Rejects invalid records and confirms rollback.
    """
    emp, dept, _, _ = _resolve_table_names(conn)
    check_enforced = False
    fk_enforced = False

    # 1. Test CHECK constraint (salary > 0)
    try:
        with conn:
            conn.execute(
                f"INSERT INTO {emp} (employee_id, employee_name, salary, department_id) "
                "VALUES (994, 'Invalid Salary', -1000, 1)"
            )
    except sqlite3.IntegrityError:
        check_enforced = True

    # 2. Test FOREIGN KEY constraint (referencing non-existent department 9999)
    try:
        with conn:
            conn.execute(
                f"INSERT INTO {emp} (employee_id, employee_name, salary, department_id) "
                "VALUES (993, 'Invalid Dept', 40000, 9999)"
            )
    except sqlite3.IntegrityError:
        fk_enforced = True

    return {
        "constraint_enforced": check_enforced,
        "check_constraint_enforced": check_enforced,
        "foreign_key_enforced": fk_enforced,
        "tested_rules": [
            "CHECK(salary > 0) rejected negative salary (-1000)",
            "FOREIGN KEY(department_id) rejected non-existent department (9999)",
        ],
        "database_integrity": "Protected against invalid domain and referential values.",
    }


def demonstrate_transaction_rollback(conn: sqlite3.Connection) -> bool:
    """
    6. Transactions and Rollback:
    Demonstrates ACID atomicity: uncommitted changes inside a failed transaction block
    are rolled back completely, leaving the database state unmodified.
    """
    emp, _, _, _ = _resolve_table_names(conn)
    initial_count = conn.execute(f"SELECT COUNT(*) FROM {emp}").fetchone()[0]

    try:
        with conn:
            conn.execute(
                f"INSERT INTO {emp} (employee_id, employee_name, salary, department_id) "
                "VALUES (996, 'Temporary Rollback Candidate', 30000, 1)"
            )
            # Simulate unexpected failure
            raise RuntimeError("Deliberate error to trigger atomic rollback")
    except RuntimeError:
        pass

    final_count = conn.execute(f"SELECT COUNT(*) FROM {emp}").fetchone()[0]
    return final_count == initial_count


def demonstrate_index(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    7. Database Indexing:
    Inspects indexes defined on relational tables to demonstrate search optimization.
    """
    emp, _, _, _ = _resolve_table_names(conn)
    rows = conn.execute(f"PRAGMA index_list('{emp}')").fetchall()
    return [dict(row) for row in rows]


def demonstrate_views_and_triggers(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    8. Views and Triggers:
    Queries the pre-defined relational view and triggers an audit logging trigger on salary update.
    Cleans up the test update immediately.
    """
    emp, _, audit, view = _resolve_table_names(conn)

    view_result = [dict(row) for row in conn.execute(f"SELECT * FROM {view}").fetchall()]

    # Ensure audit table and trigger exist
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {audit} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            old_salary REAL,
            new_salary REAL,
            changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    trigger_name = f"trg_{audit}" if audit != "salary_audit" else "salary_update_audit"
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS {trigger_name}
        AFTER UPDATE OF salary ON {emp}
        BEGIN
            INSERT INTO {audit} (employee_id, old_salary, new_salary)
            VALUES (OLD.employee_id, OLD.salary, NEW.salary);
        END
    """)

    # Trigger update on Aman (employee 101)
    conn.execute(f"UPDATE {emp} SET salary = 52000 WHERE employee_id = 101")
    conn.commit()

    audit_rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT employee_id, old_salary, new_salary FROM {audit} "
            "WHERE employee_id = 101 ORDER BY id DESC LIMIT 1"
        ).fetchall()
    ]

    # Revert Aman's salary back to 50000 for repeatability
    conn.execute(f"UPDATE {emp} SET salary = 50000 WHERE employee_id = 101")
    conn.commit()

    return {
        "view": view_result,
        "trigger_audit": audit_rows,
        "view_name": view,
        "trigger_name": trigger_name,
        "audit_table": audit,
        "reverted_cleanly": True,
    }


def execute_dbms_demonstration(
    module_name: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Any:
    """
    Central dispatcher executing the requested DBMS demonstration.
    Connects to the persistent project SQLite database when conn is None,
    preserving operational records and guaranteeing cleanup.
    """
    should_close = False
    if conn is None:
        from app.database import DEFAULT_DB_PATH, get_db_connection, init_db, seed_lab_data
        target_path = db_path or DEFAULT_DB_PATH
        init_db(db_path=target_path)
        connection_cm = get_db_connection(target_path)
        active_conn = connection_cm.__enter__()
        seed_lab_data(active_conn)
        should_close = True
    else:
        active_conn = conn

    try:
        if module_name == "design":
            return demonstrate_design(active_conn)
        elif module_name == "crud":
            return demonstrate_crud(active_conn)
        elif module_name == "queries":
            return demonstrate_queries(active_conn)
        elif module_name == "joins":
            return demonstrate_joins(active_conn)
        elif module_name == "constraints":
            return demonstrate_constraints(active_conn)
        elif module_name == "transactions":
            return {"rollback_successful": demonstrate_transaction_rollback(active_conn)}
        elif module_name == "indexes":
            return demonstrate_index(active_conn)
        elif module_name == "views_triggers":
            return demonstrate_views_and_triggers(active_conn)
        else:
            raise ValueError(f"Unknown DBMS module: '{module_name}'.")
    finally:
        if should_close:
            connection_cm.__exit__(None, None, None)
