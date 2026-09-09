import os
import contextlib
import contextvars
from pathlib import Path

APP_ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))).resolve()
APP_INTERNAL_NAMES = {
    ".git", ".github", "agents", "backend", "core", "frontend", "kk",
    "skills", "tests", "chat.py", "language_docs.json", "main.py",
    "pytest.ini", "README.md", "requirements.txt", "run_studio.bat",
    "start_studio.ps1",
}
DEFAULT_WORKSPACES = [str(APP_ROOT)]
configured_roots = os.getenv("KK_WORKSPACE_ROOTS", "")
WORKSPACE_ROOTS_CONFIGURED = bool(configured_roots.strip())
ALLOWED_WORKSPACES = [
    os.path.abspath(root.strip())
    for root in configured_roots.split(os.pathsep)
    if root.strip()
] or DEFAULT_WORKSPACES
BLOCKED_COMMANDS = ["system32", "syswow64", "rmdir /s /q", "format", "del /s /q", "reg delete", "shutdown"]
_active_workspace = contextvars.ContextVar("active_workspace", default=None)


@contextlib.contextmanager
def workspace_context(workspace: str | None):
    """Ustawia workspace tylko na czas wykonania bieżącego narzędzia."""
    token = _active_workspace.set(os.path.abspath(workspace) if workspace else None)
    try:
        yield
    finally:
        _active_workspace.reset(token)


def unrestricted_workspace_enabled() -> bool:
    """Zwraca, czy uruchomienie jawnie włączyło dostęp do całego hosta."""
    return os.getenv("KK_WINDOWS_HOST", "0").lower() in {"1", "true", "yes"}

def validate_path(target_path: str) -> bool:
    """Sprawdza, czy ścieżka znajduje się w dozwolonych obszarach roboczych (sandboxach)."""
    try:
        # Resolve any symlinks and relative path components
        abs_target = Path(target_path).resolve()
        if unrestricted_workspace_enabled():
            return abs_target.exists()
        active_workspace = _active_workspace.get()
        if active_workspace and os.path.commonpath((str(abs_target), active_workspace)) == active_workspace:
            return True
        return any(
            os.path.commonpath((str(abs_target), workspace)) == workspace
            for workspace in ALLOWED_WORKSPACES
        )
    except Exception:
        return False


def is_browsable_directory(target_path: str) -> bool:
    """Pozwala przeglądać istniejące katalogi, z wyjątkiem katalogu aplikacji."""
    try:
        resolved = Path(target_path).resolve()
        return resolved.is_dir() and is_visible_workspace_path(str(resolved))
    except (OSError, ValueError):
        return False


def filesystem_roots() -> list[str]:
    """Zwraca korzenie dostępnych dysków dla przeglądarki folderów."""
    if os.name == "nt":
        import string
        return [f"{drive}:\\" for drive in string.ascii_uppercase if os.path.isdir(f"{drive}:\\")]
    return ["/"]


def is_visible_workspace_path(target_path: str) -> bool:
    """Ukrywa pliki aplikacji, pozostawiając widoczne foldery użytkownika."""
    try:
        resolved = Path(target_path).resolve()
        if resolved == APP_ROOT:
            return False
        if APP_ROOT not in resolved.parents:
            return True
        relative = resolved.relative_to(APP_ROOT)
        return not relative.parts or relative.parts[0] not in APP_INTERNAL_NAMES
    except (OSError, ValueError):
        return False

def sanitize_command(command: str) -> bool:
    cmd_lower = command.lower()
    return not any(blocked in cmd_lower for blocked in BLOCKED_COMMANDS)
