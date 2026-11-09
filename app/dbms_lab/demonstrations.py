"""Educational DBMS demonstrations using an isolated SQLite database."""

import sqlite3


def create_demo_database():
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


def demonstrate_joins(conn):
    return [
        dict(row) for row in conn.execute("""
            SELECT e.employee_name, d.department_name
            FROM employees e
            INNER JOIN departments d
            ON e.department_id = d.department_id
        """)
    ]


def demonstrate_aggregation(conn):
    return [
        dict(row) for row in conn.execute("""
            SELECT department_id,
                   COUNT(*) AS employee_count,
                   AVG(salary) AS average_salary
            FROM employees
            GROUP BY department_id
        """)
    ]


def demonstrate_view(conn):
    return [
        dict(row) for row in conn.execute(
            "SELECT * FROM employee_department_view"
        )
    ]


def demonstrate_index(conn):
    return [
        dict(row) for row in conn.execute(
            "PRAGMA index_list('employees')"
        )
    ]


def demonstrate_transaction_rollback(conn):
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


def demonstrate_constraints(conn):
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
