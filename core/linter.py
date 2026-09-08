"""
core/linter.py – Analiza statyczna kodu po zapisie pliku.

Kolejność próbowania linterów:
  1. ruff (najszybszy, najdokładniejszy)
  2. flake8 (fallback)
  3. py_compile (wbudowany w Python – sprawdza przynajmniej składnię)

Zwraca listę błędów w ujednoliconym formacie:
  [{"line": N, "col": N, "code": "...", "message": "..."}]
"""
import os
import subprocess
import py_compile
import json
import sys
from typing import List


LintError = dict  # {"line": int, "col": int, "code": str, "message": str}


def _run_ruff(path: str) -> List[LintError] | None:
    """Próbuje uruchomić ruff. Zwraca None jeśli ruff nie jest zainstalowany."""
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", path],
            capture_output=True, text=True, timeout=15
        )
        # ruff exits with 1 when issues found, that's fine
        if result.stdout:
            raw = json.loads(result.stdout)
            errors = []
            for item in raw:
                errors.append({
                    "line": item.get("location", {}).get("row", 0),
                    "col": item.get("location", {}).get("column", 0),
                    "code": item.get("code", "?"),
                    "message": item.get("message", ""),
                })
            return errors
        return []
    except FileNotFoundError:
        return None  # ruff nie zainstalowany
    except Exception:
        return None


def _run_flake8(path: str) -> List[LintError] | None:
    """Próbuje uruchomić flake8. Zwraca None jeśli flake8 nie jest zainstalowany."""
    try:
        result = subprocess.run(
            ["flake8", "--format=%(row)d:%(col)d:%(code)s:%(text)s", path],
            capture_output=True, text=True, timeout=15
        )
        errors = []
        for line in result.stdout.splitlines():
            parts = line.split(":", 3)
            if len(parts) >= 4:
                try:
                    errors.append({
                        "line": int(parts[0]),
                        "col": int(parts[1]),
                        "code": parts[2],
                        "message": parts[3].strip(),
                    })
                except ValueError:
                    pass
        return errors
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_py_compile(path: str) -> List[LintError]:
    """Fallback: sprawdza tylko składnię Pythona (wbudowany moduł)."""
    try:
        py_compile.compile(path, doraise=True)
        return []
    except py_compile.PyCompileError as e:
        # Format: "  File "<path>", line N\n    <code>\n..."
        msg = str(e)
        line_num = 0
        try:
            import re
            m = re.search(r"line (\d+)", msg)
            if m:
                line_num = int(m.group(1))
        except Exception:
            pass
        return [{"line": line_num, "col": 0, "code": "SyntaxError", "message": msg}]


def run_linter(path: str) -> List[LintError]:
    """
    Uruchamia analizę statyczną pliku. Próbuje kolejno: ruff → flake8 → py_compile.
    Zwraca listę błędów (pusta = brak problemów).
    Działa tylko na plikach .py.
    """
    if not path.endswith(".py"):
        return []
    if not os.path.isfile(path):
        return []

    # Próba 1: ruff
    result = _run_ruff(path)
    if result is not None:
        return result

    # Próba 2: flake8
    result = _run_flake8(path)
    if result is not None:
        return result

    # Próba 3: py_compile (zawsze dostępny)
    return _run_py_compile(path)


def format_lint_errors(errors: List[LintError]) -> str:
    """Formatuje listę błędów jako czytelny tekst dla agenta."""
    if not errors:
        return "✅ Brak błędów składniowych ani lintingowych."
    lines = [f"⚠️ Znaleziono {len(errors)} błąd(ów) lintera:"]
    for e in errors:
        lines.append(f"  Linia {e['line']}, kol {e['col']} [{e['code']}]: {e['message']}")
    return "\n".join(lines)
