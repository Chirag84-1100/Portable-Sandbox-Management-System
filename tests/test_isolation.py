import os
import sys
import tempfile
import unittest
from pathlib import Path

from app.sandbox import (
    SANDBOXES_ROOT,
    build_isolated_command,
    ensure_sandbox_dir,
)


class TestIsolation(unittest.TestCase):
    def test_command_uses_bubblewrap_and_namespaces(self):
        workspace = ensure_sandbox_dir(
            "isolation_unit_test_workspace"
        )
        cmd = build_isolated_command(
            [sys.executable, "-c", "print('isolated')"],
            workspace,
        )

        self.assertTrue(cmd[0].endswith("bwrap"))
        self.assertIn("--unshare-all", cmd)
        self.assertIn("--ro-bind", cmd)
        self.assertIn("--bind", cmd)
        self.assertIn("--tmpfs", cmd)
        self.assertIn("--", cmd)
        self.assertEqual(cmd[-1], "print('isolated')")

    def test_workspace_is_inside_sandbox_root(self):
        workspace = ensure_sandbox_dir(
            "isolation_unit_test_workspace"
        )
        self.assertTrue(workspace.is_relative_to(SANDBOXES_ROOT))

    def test_missing_bwrap_fails_closed(self):
        from unittest.mock import patch

        workspace = ensure_sandbox_dir(
            "isolation_unit_test_workspace"
        )
        with patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Isolation unavailable"):
                build_isolated_command(
                    [sys.executable, "-c", "print(1)"],
                    workspace,
                )


if __name__ == "__main__":
    unittest.main()
