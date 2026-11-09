import os
import tempfile
from pathlib import Path

MARKER_NAME = "USB_MARKER"
MARKER_CONTENT = "PORTABLE_SANDBOX_STORAGE_V1"


def get_storage_root():
    configured = os.environ.get("SANDBOX_DATA_ROOT")
    if not configured:
        return None
    return Path(configured).expanduser()


def validate_portable_storage(root=None):
    configured_root = root if root is not None else get_storage_root()

    if configured_root is None:
        raise RuntimeError("Portable storage path is not configured.")

    root = Path(configured_root).expanduser()

    try:
        if not root.is_dir():
            raise RuntimeError("USB storage is unavailable.")

        marker = root / MARKER_NAME

        if not marker.is_file():
            raise RuntimeError("USB storage marker is missing.")

        if marker.read_text(encoding="utf-8").strip() != MARKER_CONTENT:
            raise RuntimeError("USB storage marker is invalid.")

        # A unique temporary file prevents concurrent requests
        # from interfering with each other's write checks.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".portable_storage_check_",
            dir=str(root),
            delete=True
        ) as test_file:
            test_file.write("ok")
            test_file.flush()

    except OSError as exc:
        raise RuntimeError(
            "USB storage is unavailable or not writable."
        ) from exc

    return root.resolve()
