"""Bezpieczne narzędzia wykonawcze agenta.

Kod wygenerowany przez model nie jest uruchamiany bezpośrednio na hoście.
Sandbox wymaga Dockera, montuje wyłącznie bieżący workspace i domyślnie
blokuje sieć. Formatowanie i operacje Git działają lokalnie, bo modyfikują
lub opisują repozytorium użytkownika, ale nie przyjmują poleceń powłoki.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from core.security import sanitize_command, unrestricted_workspace_enabled, validate_path

MAX_TOOL_OUTPUT_CHARS = max(1000, int(os.getenv("KK_MAX_TOOL_OUTPUT_CHARS", "20000")))
COMMAND_TIMEOUT_SECONDS = min(
    600,
    max(1, int(os.getenv("KK_COMMAND_TIMEOUT_SECONDS", "120"))),
)


def _result(success: bool, **data: Any) -> str:
    result = {"success": success, **data}
    truncated = False
    for key in ("stdout", "stderr", "output"):
        value = result.get(key)
        if isinstance(value, str) and len(value) > MAX_TOOL_OUTPUT_CHARS:
            result[key] = value[:MAX_TOOL_OUTPUT_CHARS] + "\n[output truncated]"
            truncated = True
    if truncated:
        result["output_truncated"] = True
    return json.dumps(result, ensure_ascii=False)


def _directory_state(path: str) -> dict:
    """Zwraca krótki stan katalogu po wykonaniu polecenia."""
    try:
        entries = sorted(os.scandir(path), key=lambda entry: entry.name.lower())
        return {
            "cwd": os.path.abspath(path),
            "dirs": [entry.name for entry in entries if entry.is_dir()][:200],
            "files": [entry.name for entry in entries if entry.is_file()][:200],
        }
    except OSError as error:
        return {"cwd": os.path.abspath(path), "error": str(error)}


def _workspace(cwd: str) -> str | None:
    path = os.path.abspath(cwd or os.getcwd())
    return path if validate_path(path) and os.path.isdir(path) else None


def run_sandbox_tool(
    command: str,
    cwd: str = ".",
    image: str = "python:3.12-slim",
    network: bool = False,
    timeout: int = 120,
) -> str:
    """Uruchamia polecenie w izolowanym kontenerze Docker.

    Brak Dockera jest błędem, nigdy powodem do uruchomienia komendy na hoście.
    Sieć trzeba włączyć jawnie, np. do instalacji zależności w kontenerze.
    """
    workspace = _workspace(cwd)
    if not workspace:
        return _result(False, error="Nieprawidłowy katalog roboczy sandboxa.")
    if not command or not sanitize_command(command):
        return _result(False, error="Polecenie jest puste albo zawiera zablokowaną operację.")
    if not image or any(char in image for char in " ;|&\n\r"):
        return _result(False, error="Nieprawidłowa nazwa obrazu Docker.")
    if shutil.which("docker") is None:
        return _result(
            False,
            error="Docker jest wymagany. Polecenie nie zostało uruchomione na hoście.",
            directory_state=_directory_state(workspace),
        )

    docker_command = [
        "docker", "run", "--rm", "--init",
        "--cpus=1", "--memory=768m", "--pids-limit=128",
        "--security-opt=no-new-privileges",
        "-v", f"{workspace}:/workspace:rw", "-w", "/workspace",
    ]
    if not network:
        docker_command.append("--network=none")
    docker_command.extend([image, "sh", "-lc", command])

    try:
        process = subprocess.run(
            docker_command,
            capture_output=True,
            text=True,
            timeout=min(COMMAND_TIMEOUT_SECONDS, max(1, min(timeout, 600))),
        )
        return _result(
            process.returncode == 0,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            sandbox=True,
            network=network,
            directory_state=_directory_state(workspace),
        )
    except subprocess.TimeoutExpired:
        return _result(False, error=f"Sandbox przekroczył limit czasu ({timeout}s).", sandbox=True)
    except Exception as error:
        return _result(False, error=f"Błąd uruchamiania sandboxa: {error}", sandbox=True)


def run_command_tool(command: str, cwd: str = ".") -> str:
    """Uruchamia komendę w sandboxie albo bezpośrednio przez PowerShell na Windowsie."""
    if unrestricted_workspace_enabled() and os.name == "nt":
        workspace = _workspace(cwd)
        if not workspace:
            return _result(False, error="Nieprawidłowy katalog roboczy Windows.")
        if not command or not sanitize_command(command):
            return _result(False, error="Polecenie jest puste albo zawiera zablokowaną operację.")

        powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not powershell:
            return _result(False, error="Nie znaleziono PowerShell (powershell.exe/pwsh.exe).")
        wrapped_command = f"$ErrorActionPreference='Continue'; {command}; (Get-Location).Path"
        try:
            process = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wrapped_command],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                encoding="utf-8",
                errors="replace",
            )
            lines = process.stdout.splitlines()
            current_directory = lines.pop().strip() if lines else workspace
            return _result(
                process.returncode == 0,
                returncode=process.returncode,
                stdout="\n".join(lines),
                stderr=process.stderr,
                cwd=current_directory,
                shell="powershell",
                directory_state=_directory_state(current_directory),
            )
        except subprocess.TimeoutExpired:
            return _result(
                False,
                error=f"PowerShell przekroczył limit czasu ({COMMAND_TIMEOUT_SECONDS}s).",
                cwd=workspace,
            )
        except Exception as error:
            return _result(False, error=f"Błąd uruchamiania PowerShell: {error}", cwd=workspace)
    return run_sandbox_tool(command, cwd=cwd)


def _run_local(args: list[str], cwd: str, timeout: int = COMMAND_TIMEOUT_SECONDS) -> str:
    try:
        process = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return _result(
            process.returncode == 0,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            command=args,
        )
    except FileNotFoundError:
        return _result(False, error=f"Brak narzędzia: {args[0]}", command=args)
    except subprocess.TimeoutExpired:
        return _result(False, error=f"Przekroczono limit czasu ({timeout}s).", command=args)
    except Exception as error:
        return _result(False, error=str(error), command=args)


def format_file_tool(path: str) -> str:
    """Uruchamia właściwy formater i zapisuje poprawiony plik."""
    if not validate_path(path) or not os.path.isfile(path):
        return _result(False, error="Plik nie istnieje albo jest poza workspace.")
    extension = os.path.splitext(path)[1].lower()
    cwd = os.path.dirname(os.path.abspath(path))
    formatters = {
        ".py": ["black", path],
        ".js": ["npx", "prettier", "--write", path],
        ".jsx": ["npx", "prettier", "--write", path],
        ".ts": ["npx", "prettier", "--write", path],
        ".tsx": ["npx", "prettier", "--write", path],
        ".html": ["npx", "prettier", "--write", path],
        ".css": ["npx", "prettier", "--write", path],
        ".go": ["gofmt", "-w", path],
        ".c": ["clang-format", "-i", path],
        ".h": ["clang-format", "-i", path],
        ".cc": ["clang-format", "-i", path],
        ".cpp": ["clang-format", "-i", path],
        ".cs": ["dotnet", "format", "--include", path],
    }
    args = formatters.get(extension)
    if not args:
        return _result(False, error=f"Brak formatera dla rozszerzenia {extension}.")
    return _run_local(args, cwd)


def run_tests_tool(command: str = "", cwd: str = ".") -> str:
    """Uruchamia testy w sandboxie; bez komendy dobiera typowy runner."""
    entries = os.listdir(cwd or ".") if os.path.isdir(cwd or ".") else []
    if not command:
        if os.path.exists(os.path.join(cwd, "pytest.ini")) or os.path.isdir(os.path.join(cwd, "tests")):
            command = "pytest -q"
        elif os.path.exists(os.path.join(cwd, "package.json")):
            command = "npm test -- --runInBand"
        elif os.path.exists(os.path.join(cwd, "go.mod")):
            command = "go test ./..."
        elif any(entry.endswith(".csproj") for entry in entries):
            command = "dotnet test"
        else:
            command = "python -m unittest discover -v"
    return run_sandbox_tool(command, cwd=cwd)


def run_coverage_tool(command: str = "pytest -q", cwd: str = ".") -> str:
    """Uruchamia testy z coverage w sandboxie."""
    test_command = command.strip()
    if test_command.startswith("python -m "):
        test_command = test_command.removeprefix("python -m ")
    if not test_command.startswith("pytest"):
        return _result(False, error="Coverage obsługuje obecnie runner pytest.")
    coverage_command = f"coverage run -m {test_command} && coverage report -m"
    return run_sandbox_tool(coverage_command, cwd=cwd)


def git_tool(action: str, cwd: str = ".", value: str = "") -> str:
    """Wykonuje ograniczony zestaw operacji Git bez powłoki."""
    workspace = _workspace(cwd)
    if not workspace:
        return _result(False, error="Nieprawidłowy katalog repozytorium.")
    actions = {
        "status": ["git", "status", "--short"],
        "diff": ["git", "diff", "--stat"],
        "log": ["git", "log", "-5", "--oneline"],
        "branch": ["git", "branch", "--show-current"],
        "pull": ["git", "pull", "--ff-only"],
        "push": ["git", "push"],
        "checkout": ["git", "switch", value],
        "create_branch": ["git", "switch", "-c", value],
        "add": ["git", "add", "--", value],
        "commit": ["git", "commit", "-m", value],
    }
    args = actions.get(action)
    if not args or (action in {"checkout", "create_branch", "add", "commit"} and not value):
        return _result(False, error="Nieobsługiwana akcja Git albo brak wartości.")
    return _run_local(args, workspace, timeout=120)