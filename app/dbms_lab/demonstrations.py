"""Educational DBMS demonstrations using an isolated SQLite database."""

import sqlite3
from typing import Any, Dict, List, Optional


def create_demo_database() -> sqlite3.Connection:
    """Creates an in-memory SQLite database populated with educational relational tables."""
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
            FOREIGN KEY(department_id)
                REFERENCES departments(department_id)
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

        CREATE INDEX idx_employee_department
        ON employees(department_id);

        CREATE VIEW employee_department_view AS
        SELECT e.employee_id, e.employee_name,
               e.salary, d.department_name
        FROM employees e
        JOIN departments d
        ON e.department_id = d.department_id;
    """)

    return conn


def demonstrate_design(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """1. Database Design: Inspect relational tables and views."""
    return [
        dict(row) for row in conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view') ORDER BY type, name"
        )
    ]


def demonstrate_crud(conn: sqlite3.Connection) -> Dict[str, Any]:
    """2. CRUD Operations: INSERT, UPDATE, SELECT, and DELETE demonstration."""
    conn.execute(
        "INSERT INTO employees VALUES (105, 'Demo User', 45000, 1)"
    )
    conn.execute(
        "UPDATE employees SET salary = 48000 WHERE employee_id = 105"
    )
    inserted = dict(conn.execute(
        "SELECT * FROM employees WHERE employee_id = 105"
    ).fetchone())
    conn.execute("DELETE FROM employees WHERE employee_id = 105")
    return {
        "after_insert_and_update": inserted,
        "deleted_successfully": conn.execute(
            "SELECT COUNT(*) FROM employees WHERE employee_id = 105"
        ).fetchone()[0] == 0,
    }


def demonstrate_queries(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """3. SQL Queries & Filtering: SELECT, WHERE, ORDER BY demonstration."""
    return [
        dict(row) for row in conn.execute(
            "SELECT employee_name, salary FROM employees "
            "WHERE salary >= 50000 ORDER BY salary DESC"
        )
    ]


def demonstrate_joins(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """4. SQL Relational Joins: INNER JOIN between employees and departments."""
    return [
        dict(row) for row in conn.execute("""
            SELECT e.employee_name, d.department_name
            FROM employees e
            INNER JOIN departments d
            ON e.department_id = d.department_id
        """)
    ]


def demonstrate_aggregation(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """SQL Aggregation: COUNT(*) and AVG(salary) grouped by department."""
    return [
        dict(row) for row in conn.execute("""
            SELECT department_id,
                   COUNT(*) AS employee_count,
                   AVG(salary) AS average_salary
            FROM employees
            GROUP BY department_id
        """)
    ]


def demonstrate_view(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Display pre-created database view."""
    return [
        dict(row) for row in conn.execute(
            "SELECT * FROM employee_department_view"
        )
    ]


def demonstrate_index(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """7. Database Indexing: Inspect indexes created on employees."""
    return [
        dict(row) for row in conn.execute(
            "PRAGMA index_list('employees')"
        )
    ]


def demonstrate_transaction_rollback(conn: sqlite3.Connection) -> bool:
    """6. Transactions: Demonstrates atomic rollback discarding uncommitted changes."""
    try:
        with conn:
            conn.execute("""
                INSERT INTO employees
                VALUES (105, 'Temporary', 30000, 1)
            """)
            raise RuntimeError("Demonstrating rollback")
    except RuntimeError:
        pass

    return conn.execute("""
        SELECT COUNT(*) FROM employees WHERE employee_id = 105
    """).fetchone()[0] == 0


def demonstrate_constraints(conn: sqlite3.Connection) -> Dict[str, bool]:
    """5. Database Constraints: Demonstrates CHECK constraint violation rejection."""
    try:
        conn.execute("""
            INSERT INTO employees
            VALUES (106, 'Invalid', -1000, 1)
        """)
        conn.commit()
        return {"constraint_enforced": False}
    except sqlite3.IntegrityError:
        conn.rollback()
        return {"constraint_enforced": True}


def demonstrate_views_and_triggers(conn: sqlite3.Connection) -> Dict[str, Any]:
    """8. Views & Triggers: Queries relational view and demonstrates an audit trigger."""
    view_result = demonstrate_view(conn)

    conn.execute("""
        CREATE TABLE salary_audit (
            employee_id INTEGER,
            old_salary REAL,
            new_salary REAL
        )
    """)

    conn.execute("""
        CREATE TRIGGER salary_update_audit
        AFTER UPDATE OF salary ON employees
        BEGIN
            INSERT INTO salary_audit
            VALUES (OLD.employee_id, OLD.salary, NEW.salary);
        END
    """)

    conn.execute(
        "UPDATE employees SET salary = 52000 "
        "WHERE employee_id = 101"
    )

    audit = [
        dict(row) for row in conn.execute(
            "SELECT * FROM salary_audit"
        )
    ]

    return {
        "view": view_result,
        "trigger_audit": audit,
    }


def execute_dbms_demonstration(module_name: str, conn: Optional[sqlite3.Connection] = None) -> Any:
    """Central dispatcher executing the requested DBMS demonstration."""
    should_close = False
    if conn is None:
        conn = create_demo_database()
        should_close = True

    try:
        if module_name == "design":
            return demonstrate_design(conn)
        elif module_name == "crud":
            return demonstrate_crud(conn)
        elif module_name == "queries":
            return demonstrate_queries(conn)
        elif module_name == "joins":
            return demonstrate_joins(conn)
        elif module_name == "constraints":
            return demonstrate_constraints(conn)
        elif module_name == "transactions":
            return {"rollback_successful": demonstrate_transaction_rollback(conn)}
        elif module_name == "indexes":
            return demonstrate_index(conn)
        elif module_name == "views_triggers":
            return demonstrate_views_and_triggers(conn)
        else:
            raise ValueError("Select a valid DBMS demonstration.")
    finally:
        if should_close and conn is not None:
            conn.close()
