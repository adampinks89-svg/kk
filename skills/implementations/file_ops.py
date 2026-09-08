"""
skills/implementations/file_ops.py – Narzędzia systemu plików agenta.

Ulepszona wersja z:
  - Automatycznym tworzeniem migawki (snapshot) przed zapisem
  - Wyliczaniem diffów przez difflib (added/removed lines)
  - Zwracaniem ustrukturyzowanego JSON zamiast czystego tekstu
    - Integracją z linterem po zapisie obsługiwanego pliku źródłowego
"""
import os
import json
import difflib
from core.security import validate_path
from core.snapshot import create_snapshot
from core.linter import SUPPORTED_EXTENSIONS, run_linter, format_lint_errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_diff(old_content: str, new_content: str, filename: str) -> dict:
    """
    Wylicza diff między starą a nową wersją pliku.
    Zwraca słownik z: added, removed, diff_lines (lista {"op": "+"/"-"/" ", "content": str})
    """
    old_lines = old_content.splitlines(keepends=True) if old_content else []
    new_lines = new_content.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm=""
    ))

    added = 0
    removed = 0
    diff_lines = []

    for line in diff:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            diff_lines.append({"op": " ", "content": line})
            continue
        if line.startswith("+"):
            added += 1
            diff_lines.append({"op": "+", "content": line[1:]})
        elif line.startswith("-"):
            removed += 1
            diff_lines.append({"op": "-", "content": line[1:]})
        else:
            diff_lines.append({"op": " ", "content": line[1:] if line.startswith(" ") else line})

    return {"added": added, "removed": removed, "diff_lines": diff_lines}


# ---------------------------------------------------------------------------
# Narzędzia agenta
# ---------------------------------------------------------------------------

def list_dir_tool(path: str) -> str:
    """Listuje zawartość katalogu w dozwolonym obszarze roboczym."""
    if not validate_path(path):
        return json.dumps({
            "success": False,
            "error": f"Ścieżka {path} wykracza poza dozwolony obszar."
        })
    try:
        items = os.listdir(path)
        dirs = [i for i in items if os.path.isdir(os.path.join(path, i))]
        files = [i for i in items if os.path.isfile(os.path.join(path, i))]
        return json.dumps({
            "success": True,
            "path": path,
            "dirs": dirs,
            "files": files,
            "total": len(items)
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def read_file_tool(path: str) -> str:
    """
    Odczytuje zawartość pliku.
    Zwraca JSON z treścią i opcjonalnym kontekstem AST dla plików .py.
    """
    if not validate_path(path):
        return json.dumps({
            "success": False,
            "error": f"Ścieżka {path} wykracza poza dozwolony obszar."
        })

    content = None
    detected_encoding = "utf-8"
    encodings_to_try = ["utf-8", "cp1250", "iso-8859-2", "latin-1"]

    for enc in encodings_to_try:
        try:
            with open(path, "r", encoding=enc) as f:
                content = f.read()
            detected_encoding = enc
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    if content is None:
        return json.dumps({
            "success": False,
            "error": f"Plik '{path}' jest binarny lub ma nieobsługiwane kodowanie."
        })

    result: dict = {
        "success": True,
        "path": path,
        "content": content,
        "lines": len(content.splitlines()),
        "encoding": detected_encoding
    }

    # Dołącz mapę AST dla plików Python
    if path.endswith(".py"):
        try:
            from core.ast_analyzer import get_ast_summary
            result["ast_summary"] = get_ast_summary(path)
        except Exception:
            pass

    return json.dumps(result, ensure_ascii=False)


def write_file_tool(path: str, content: str) -> str:
    """
    Zapisuje zawartość do pliku z automatycznym:
      1. Tworzeniem migawki (backup) jeśli plik istnieje
      2. Wyliczaniem diffu (added/removed lines)
    3. Uruchomieniem właściwego lintera po zapisie pliku źródłowego

    Zwraca JSON z wynikiem operacji i statystykami diffu.
    """
    if not validate_path(path):
        return json.dumps({
            "success": False,
            "error": f"Ścieżka {path} wykracza poza dozwolony obszar.",
        })

    # 1. Wczytaj starą wersję (jeśli istnieje), zbadaj kodowanie i utwórz snapshot
    old_content = ""
    snapshot_id = None
    is_new_file = not os.path.isfile(path)
    file_encoding = "utf-8"

    if not is_new_file:
        encodings_to_try = ["utf-8", "cp1250", "iso-8859-2", "latin-1"]
        for enc in encodings_to_try:
            try:
                with open(path, "r", encoding=enc) as f:
                    old_content = f.read()
                file_encoding = enc
                break
            except Exception:
                pass

        snapshot_id = create_snapshot(path)

    # 2. Wylicz diff
    filename = os.path.basename(path)
    diff_data = _compute_diff(old_content, content, filename)

    # 3. Zapisz plik używając wykrytego kodowania
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding=file_encoding) as f:
            f.write(content)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

    # 4. Uruchom linter dla plików Python
    lint_errors = []
    lint_message = ""
    if os.path.splitext(path)[1].lower() in SUPPORTED_EXTENSIONS:
        try:
            lint_errors = run_linter(path)
            lint_message = format_lint_errors(lint_errors)
        except Exception:
            lint_message = ""

        # Jeśli są błędy lintera → odpytaj RAG
        rag_context = ""
        if lint_errors:
            try:
                from core.rag_client import fetch_context_for_lint_errors
                rag_context = fetch_context_for_lint_errors(path, lint_errors)
            except Exception:
                pass

        if rag_context:
            lint_message += f"\n\n📚 [RAG Suggestion]:\n{rag_context}"

    result = {
        "success": True,
        "path": path,
        "operation": "create" if is_new_file else "write",
        "added": diff_data["added"],
        "removed": diff_data["removed"],
        "diff_lines": diff_data["diff_lines"],
        "snapshot_id": snapshot_id,
        "lint_errors": lint_errors,
        "lint_message": lint_message,
    }

    return json.dumps(result, ensure_ascii=False)


def rollback_file_tool(snapshot_id: str) -> str:
    """Przywraca plik do poprzedniej wersji ze migawki."""
    try:
        from core.snapshot import restore_snapshot
        success, message = restore_snapshot(snapshot_id)
        return json.dumps({"success": success, "message": message})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
