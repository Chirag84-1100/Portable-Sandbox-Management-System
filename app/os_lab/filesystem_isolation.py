"""
Filesystem Security & Namespace Isolation for OS Lab.
Demonstrates operating system isolation and protection mechanisms by reusing:
- validate_sandbox_path and ensure_sandbox_dir (Boundary checking & traversal defense)
- build_isolated_command (Bubblewrap namespace unsharing and read-only mounts)
- execute_sync (Real isolated probe execution inside Bubblewrap sandbox)
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.sandbox import (
    SANDBOXES_ROOT,
    build_isolated_command,
    ensure_sandbox_dir,
    execute_sync,
    validate_sandbox_path,
)


def verify_path_boundaries(test_paths: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Demonstrates filesystem boundary enforcement against path traversal.
    Tests valid sandbox targets versus directory traversal attack vectors.
    """
    candidates = test_paths or [
        "sb_student_workspace",
        "sb_lab_demo/subproject",
        "../etc/passwd",
        "../../root/.ssh",
        "/etc/shadow",
        "/tmp",
        ".",
    ]

    results = []
    for candidate in candidates:
        try:
            resolved = validate_sandbox_path(candidate)
            results.append({
                "path": candidate,
                "resolved": str(resolved),
                "status": "ALLOWED",
                "is_safe": True,
                "reason": "Path is confined within the sandbox storage boundary.",
            })
        except ValueError as err:
            results.append({
                "path": candidate,
                "resolved": None,
                "status": "BLOCKED",
                "is_safe": False,
                "reason": str(err),
            })

    return results


def inspect_isolation_profile(target_dir: Path) -> Dict[str, Any]:
    """
    Inspects the Bubblewrap security configuration and unshared namespaces.
    """
    cmd = build_isolated_command([sys.executable, "-c", "pass"], target_dir)
    return {
        "isolation_engine": "bubblewrap (bwrap)",
        "unshared_namespaces": [
            "CLONE_NEWPID (Process ID isolation)",
            "CLONE_NEWNET (Network namespace isolation)",
            "CLONE_NEWNS (Mount namespace isolation)",
            "CLONE_NEWIPC (IPC namespace isolation)",
            "CLONE_NEWUTS (Host/domain name isolation)",
            "CLONE_NEWUSER (User namespace isolation)",
        ],
        "mount_policies": {
            "root_filesystem": "Read-Only (--ro-bind / /)",
            "workspace_directory": f"Read-Write Bind (--bind {target_dir} {target_dir})",
            "temporary_filesystem": "tmpfs (--tmpfs /tmp)",
            "device_nodes": "Isolated /dev (--dev /dev)",
            "proc_filesystem": "Isolated /proc (--proc /proc)",
        },
        "command_tokens": cmd,
    }


def demonstrate_filesystem_isolation(
    sandbox_id: int,
    working_dir: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes a real security probe inside the Bubblewrap container:
    1. Attempts to write to read-only host root / (must fail with EROFS / PermissionError).
    2. Attempts to write to sandbox workspace (must succeed).
    """
    target_dir = ensure_sandbox_dir(working_dir)
    isolation_profile = inspect_isolation_profile(target_dir)

    probe_code = (
        "import sys\n"
        "# 1. Test write to read-only root boundary\n"
        "root_write_blocked = False\n"
        "root_err_msg = ''\n"
        "try:\n"
        "    with open('/illegal_root_probe.txt', 'w') as f:\n"
        "        f.write('unauthorized')\n"
        "except OSError as e:\n"
        "    root_write_blocked = True\n"
        "    root_err_msg = str(e)\n\n"
        "# 2. Test write to allowed sandbox workspace\n"
        "workspace_write_allowed = False\n"
        "try:\n"
        "    with open('sandbox_isolation_test.txt', 'w') as f:\n"
        "        f.write('authorized sandbox write')\n"
        "    workspace_write_allowed = True\n"
        "except Exception as e:\n"
        "    workspace_write_allowed = False\n\n"
        "print(f'ROOT_BLOCKED={root_write_blocked}')\n"
        "print(f'ROOT_ERROR={root_err_msg}')\n"
        "print(f'WORKSPACE_ALLOWED={workspace_write_allowed}')\n"
    )

    run_record = execute_sync(
        sandbox_id=sandbox_id,
        command=[sys.executable, "-c", probe_code],
        working_dir=working_dir,
        timeout=5.0,
        enable_monitoring=False,
        db_path=db_path,
    )

    stdout = run_record.get("stdout", "")
    root_blocked = "ROOT_BLOCKED=True" in stdout
    workspace_allowed = "WORKSPACE_ALLOWED=True" in stdout

    return {
        "sandbox_id": sandbox_id,
        "working_dir": str(target_dir),
        "boundary_checks": verify_path_boundaries(),
        "bubblewrap_profile": isolation_profile,
        "runtime_probe": {
            "root_write_blocked": root_blocked,
            "workspace_write_allowed": workspace_allowed,
            "isolation_verified": root_blocked and workspace_allowed,
            "raw_output": stdout.strip(),
        },
    }

