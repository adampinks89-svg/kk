"""
skills/registry.py – Rejestr narzędzi agenta.

Nowe narzędzia:
  - run_linter_tool       – analiza statyczna pliku Python
  - get_ast_context_tool  – mapa struktury kodu (klasy/funkcje)
  - rollback_file_tool    – przywrócenie pliku ze migawki
"""
import json
from typing import Callable, Dict, Any

from skills.implementations.file_ops import (
    list_dir_tool,
    read_file_tool,
    write_file_tool,
    rollback_file_tool,
)
from skills.implementations.cmd_ops import run_command_tool
from core.logger import read_logs
from core.linter import run_linter, format_lint_errors
from core.ast_analyzer import get_ast_summary


# ---------------------------------------------------------------------------
# Adaptery narzędzi (upewniamy się, że zawsze zwracają str)
# ---------------------------------------------------------------------------

def _run_linter_tool(path: str) -> str:
    """Adapter: uruchamia linter i zwraca sformatowany tekst."""
    errors = run_linter(path)
    return format_lint_errors(errors)


def _get_ast_context_tool(path: str) -> str:
    """Adapter: zwraca skróconą mapę AST pliku Python."""
    return get_ast_summary(path)


# ---------------------------------------------------------------------------
# Mapowanie nazw → funkcje
# ---------------------------------------------------------------------------

SKILL_FUNCTIONS: Dict[str, Callable] = {
    "list_dir_tool": list_dir_tool,
    "read_file_tool": read_file_tool,
    "write_file_tool": write_file_tool,
    "rollback_file_tool": rollback_file_tool,
    "run_linter_tool": _run_linter_tool,
    "get_ast_context_tool": _get_ast_context_tool,
    "read_system_logs_tool": read_logs,
    "run_command_tool": run_command_tool,
}


# ---------------------------------------------------------------------------
# Definicje narzędzi w formacie Ollama
# ---------------------------------------------------------------------------

OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir_tool",
            "description": (
                "Zwraca zawartość folderu (pliki i podkatalogi). "
                "Używaj aby sprawdzić co istnieje przed odczytem lub zapisem."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ścieżka absolutna do katalogu"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_tool",
            "description": (
                "Odczytuje zawartość pliku tekstowego. "
                "Dla plików .py dołącza również mapę AST (klasy i funkcje). "
                "ZAWSZE odczytaj plik przed jego modyfikacją."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ścieżka do pliku"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file_tool",
            "description": (
                "Zapisuje nową zawartość do pliku. Automatycznie: "
                "(1) tworzy backup (snapshot), "
                "(2) wylicza diff (added/removed lines), "
                "(3) uruchamia linter po zapisie. "
                "Wymaga zatwierdzenia przez użytkownika jeśli włączony Human-in-the-Loop."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ścieżka do pliku"},
                    "content": {"type": "string", "description": "Pełna nowa zawartość pliku"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_file_tool",
            "description": (
                "Przywraca plik do poprzedniej wersji ze migawki (backup). "
                "Używaj gdy ostatnia zmiana wprowadzona przez agenta jest błędna."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "snapshot_id": {
                        "type": "string",
                        "description": "ID migawki (np. '2026-09-07_10-30-00_main.py')"
                    }
                },
                "required": ["snapshot_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_linter_tool",
            "description": (
                "Uruchamia analizę statyczną pliku Python (ruff/flake8/py_compile). "
                "Użyj po zapisaniu pliku lub gdy podejrzewasz błąd składniowy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ścieżka do pliku .py"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ast_context_tool",
            "description": (
                "Zwraca mapę struktury kodu Python: klasy, metody, funkcje, importy. "
                "Używaj zamiast read_file_tool gdy chcesz poznać API modułu bez czytania "
                "całego kodu – eliminuje halucynacje o nieistniejących metodach."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ścieżka do pliku .py"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_system_logs_tool",
            "description": (
                "Odczytuje ostatnie linie z logu systemowego agenta. "
                "Użyj gdy chcesz sprawdzić co poszło nie tak lub przejrzeć historię akcji."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "integer",
                        "description": "Liczba ostatnich linii logu (domyślnie 50)"
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command_tool",
            "description": (
                "Uruchamia polecenie lub skrypt w systemie operacyjnym (np. 'python3 calculator.py'). "
                "Używaj do testowania napisanych aplikacji okienkowych i skryptów."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Polecenie do wykonania (np. 'python3 calculator.py')"
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Katalog roboczy (domyślnie obecny katalog)"
                    }
                },
                "required": ["command"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Wykonanie narzędzia
# ---------------------------------------------------------------------------

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Wykonuje wskazane narzędzie z podanymi argumentami."""
    if tool_name not in SKILL_FUNCTIONS:
        return json.dumps({
            "success": False,
            "error": f"Narzędzie '{tool_name}' nie istnieje."
        })

    func = SKILL_FUNCTIONS[tool_name]
    try:
        result = func(**arguments)
        return str(result)
    except TypeError as e:
        return json.dumps({
            "success": False,
            "error": f"Złe argumenty dla '{tool_name}': {str(e)}"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Błąd wykonania '{tool_name}': {str(e)}"
        })
