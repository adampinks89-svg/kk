import os
from pathlib import Path

ALLOWED_WORKSPACES = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    os.path.abspath(os.getcwd())
]
BLOCKED_COMMANDS = ["system32", "syswow64", "rmdir /s /q", "format", "del /s /q", "reg delete", "shutdown"]

def validate_path(target_path: str) -> bool:
    """Sprawdza, czy ścieżka znajduje się w dozwolonych obszarach roboczych (sandboxach)."""
    try:
        # Resolve any symlinks and relative path components
        abs_target = Path(target_path).resolve()
        return any(
            os.path.commonpath((str(abs_target), workspace)) == workspace
            for workspace in ALLOWED_WORKSPACES
        )
    except Exception:
        return False

def sanitize_command(command: str) -> bool:
    cmd_lower = command.lower()
    return not any(blocked in cmd_lower for blocked in BLOCKED_COMMANDS)
