"""
USB-Based Portable Sandbox Management System
Live mentor demonstration using actual project modules.
"""

import os
import sys
import json
import shutil
import traceback
from pathlib import Path
from threading import Thread

from app.storage import validate_portable_storage
from app.database import (
    DEFAULT_DB_PATH,
    init_db,
    get_db_connection,
    get_user_by_username,
    create_user,
    get_execution_run_by_id,
    get_metrics_for_run,
    list_recent_activity,
)
from app.sandbox import get_or_create_default_sandbox, ensure_sandbox_dir

from app.os_lab.scheduling import fcfs, sjf, round_robin
from app.os_lab.memory import allocate_memory
from app.os_lab.deadlock import bankers_algorithm
from app.os_lab.synchronization import BoundedBuffer
from app.os_lab.ipc import pipe_communication
from app.os_lab.process_control import run_process_demonstration
from app.os_lab.filesystem_isolation import demonstrate_filesystem_isolation
from app.os_lab.signals_telemetry import (
    demonstrate_signal_termination,
    demonstrate_resource_telemetry,
)
from app.dbms_lab.demonstrations import execute_dbms_demonstration


DB_PATH = DEFAULT_DB_PATH
WORKSPACE = None
SANDBOX_ID = None
RESULTS = {"OS": {}, "DBMS": {}}


def heading(title):
    print("\n" + "=" * 65)
    print(title)
    print("=" * 65)


def show_result(name, result):
    print(f"\n[RESULT] {name}")
    print(json.dumps(result, indent=2, default=str))


def run_module(category, name, function):
    try:
        result = function()
        RESULTS[category][name] = "PASS"
        show_result(name, result)
        return result
    except Exception as exc:
        RESULTS[category][name] = f"FAIL: {exc}"
        print(f"\n[FAILED] {name}: {exc}")
        traceback.print_exc()
        return None


def main():
    global WORKSPACE, SANDBOX_ID

    heading("PORTABLE SANDBOX - LIVE SYSTEM DEMONSTRATION")

    # 1. Validate portable USB storage.
    heading("1. PORTABLE USB STORAGE")
    root = validate_portable_storage()
    print("USB storage validated:", root)
    print("Marker:", (root / "USB_MARKER").read_text().strip())
    print("Database path:", DB_PATH)
    print("Bubblewrap available:", bool(shutil.which("bwrap")))

    # 2. Initialize existing database and dedicated demo identity.
    heading("2. DATABASE AND DEMO WORKSPACE")
    init_db(db_path=DB_PATH)

    username = "mentor_demo"
    user = get_user_by_username(username, db_path=DB_PATH)

    if user is None:
        user_id = create_user(
            username,
            os.urandom(24).hex(),
            role="user",
            db_path=DB_PATH,
        )
        print("Created dedicated mentor demonstration account.")
    else:
        user_id = user["id"]
        print("Reusing dedicated mentor demonstration account.")

    sandbox = get_or_create_default_sandbox(user_id, db_path=DB_PATH)
    SANDBOX_ID = sandbox["id"]
    WORKSPACE = str(ensure_sandbox_dir(sandbox["working_dir"]))

    print("Sandbox ID:", SANDBOX_ID)
    print("Workspace:", WORKSPACE)

    # 3. OS MODULE 1 - CPU scheduling.
    heading("3. OS MODULE 1 - CPU SCHEDULING")
    processes = [
        {"pid": "P1", "arrival": 0, "burst": 5},
        {"pid": "P2", "arrival": 1, "burst": 3},
        {"pid": "P3", "arrival": 2, "burst": 1},
    ]

    run_module("OS", "CPU Scheduling - FCFS", lambda: fcfs(processes))
    run_module("OS", "CPU Scheduling - SJF", lambda: sjf(processes))
    run_module("OS", "CPU Scheduling - Round Robin",
               lambda: round_robin(processes, 2))

    # 4. OS MODULE 2 - Memory allocation.
    heading("4. OS MODULE 2 - MEMORY ALLOCATION")
    run_module(
        "OS", "Memory Allocation",
        lambda: allocate_memory(
            [100, 500, 200, 300, 600],
            [212, 417, 112, 426],
            "first_fit",
        ),
    )

    # 5. OS MODULE 3 - Deadlock avoidance.
    heading("5. OS MODULE 3 - BANKER'S ALGORITHM")
    run_module(
        "OS", "Deadlock Avoidance",
        lambda: bankers_algorithm(
            [3, 3, 2],
            [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]],
            [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]],
        ),
    )

    # 6. OS MODULE 4 - Producer-consumer synchronization.
    heading("6. OS MODULE 4 - SYNCHRONIZATION")
    def synchronization_demo():
        buffer = BoundedBuffer(capacity=2)
        items = [10, 20, 30, 40]
        sentinel = None

        def producer():
            for item in items:
                buffer.produce(item)
            buffer.produce(sentinel)

        thread = Thread(target=producer)
        thread.start()

        consumed = []
        while True:
            item = buffer.consume()
            if item is sentinel:
                break
            consumed.append(item)

        thread.join()
        return {"consumed_items": consumed, "buffer_status": buffer.get_status()}

    run_module("OS", "Synchronization", synchronization_demo)

    # 7. OS MODULE 5 - Inter-process communication.
    heading("7. OS MODULE 5 - IPC")
    run_module(
        "OS", "Inter-Process Communication",
        lambda: pipe_communication(
            "Hello from the Portable Sandbox",
            sandbox_id=SANDBOX_ID,
            working_dir=WORKSPACE,
            db_path=DB_PATH,
        ),
    )

    # 8. OS MODULE 6 - Actual isolated process lifecycle.
    heading("8. OS MODULE 6 - PROCESS MANAGEMENT")
    run_module(
        "OS", "Process Lifecycle",
        lambda: run_process_demonstration(
            sandbox_id=SANDBOX_ID,
            command=[sys.executable, "-c",
                     "print('Hello from inside the Portable Sandbox')"],
            working_dir=WORKSPACE,
            timeout=10,
            db_path=DB_PATH,
        ),
    )

    # 9. OS MODULE 7 - Filesystem isolation.
    heading("9. OS MODULE 7 - FILESYSTEM ISOLATION")
    run_module(
        "OS", "Filesystem Isolation",
        lambda: demonstrate_filesystem_isolation(
            sandbox_id=SANDBOX_ID,
            working_dir=WORKSPACE,
            db_path=DB_PATH,
        ),
    )

    # 10. OS MODULE 8 - Signals and resource monitoring.
    heading("10. OS MODULE 8 - SIGNALS AND RESOURCE MONITORING")
    run_module(
        "OS", "Signal Termination",
        lambda: demonstrate_signal_termination(
            sandbox_id=SANDBOX_ID,
            working_dir=WORKSPACE,
            db_path=DB_PATH,
        ),
    )
    telemetry = run_module(
        "OS", "Resource Telemetry",
        lambda: demonstrate_resource_telemetry(
            sandbox_id=SANDBOX_ID,
            working_dir=WORKSPACE,
            db_path=DB_PATH,
        ),
    )

    # 11. DBMS - All eight demonstrations.
    heading("11. DBMS LAB - EIGHT MODULES")
    dbms_modules = [
        "design",
        "crud",
        "queries",
        "joins",
        "constraints",
        "transactions",
        "indexes",
        "views_triggers",
    ]

    for module in dbms_modules:
        run_module(
            "DBMS",
            f"DBMS - {module}",
            lambda module=module: execute_dbms_demonstration(
                module_name=module,
                db_path=DB_PATH,
            ),
        )

    # 12. Verify actual persisted records.
    heading("12. DATABASE PERSISTENCE AND AUDIT")
    with get_db_connection(DB_PATH) as conn:
        execution_count = conn.execute(
            "SELECT COUNT(*) FROM execution_runs WHERE sandbox_id = ?",
            (SANDBOX_ID,),
        ).fetchone()[0]

        metric_count = conn.execute(
            """
            SELECT COUNT(*) FROM resource_metrics
            WHERE run_id IN (
                SELECT id FROM execution_runs WHERE sandbox_id = ?
            )
            """,
            (SANDBOX_ID,),
        ).fetchone()[0]

        activity_count = conn.execute(
            "SELECT COUNT(*) FROM activity_logs WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]

        print("Execution records:", execution_count)
        print("Resource metric records:", metric_count)
        print("User activity records:", activity_count)

    recent_activity = list_recent_activity(
    limit=15, db_path=DB_PATH
    )
    print("Recent system activity entries:", len(recent_activity))

    for activity in recent_activity:
        print(
            f"  [{activity['action']}] "
            f"User ID: {activity['user_id']} | "
            f"{activity['details']}"
        )

    # 13. Final report.
    heading("13. FINAL DEMONSTRATION SUMMARY")
    for category, modules in RESULTS.items():
        print(f"\n{category} MODULES")
        for name, status in modules.items():
            print(f"  {name}: {status}")

    print("\nUSB:", root)
    print("Database:", DB_PATH)
    print("Sandbox ID:", SANDBOX_ID)
    print("Workspace:", WORKSPACE)
    print("Execution records:", execution_count)
    print("Resource metrics:", metric_count)
    print("Activity records:", activity_count)

    passed = sum(v == "PASS" for group in RESULTS.values()
                 for v in group.values())
    failed = sum(v != "PASS" for group in RESULTS.values()
                 for v in group.values())

    print(f"\nTOTAL: {passed} passed, {failed} failed")
    print("\nDemonstration completed. Review any failed modules above.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nDEMONSTRATION COULD NOT COMPLETE:", exc)
        traceback.print_exc()
        sys.exit(1)
