"""
core/snapshot.py – System migawek (rollback) dla plików.

Przed każdą modyfikacją pliku tworzony jest backup w:
  workspace/snapshots/<timestamp>_<basename>.bak

API:
  create_snapshot(path) -> snapshot_id | None
  list_snapshots()      -> [{"id": ..., "original_path": ..., "created_at": ...}]
  restore_snapshot(snapshot_id, target_path) -> (success, message)
"""
import os
import shutil
import json
import uuid
from datetime import datetime
from pathlib import Path

# Katalog z migawkami względem katalogu głównego projektu
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOTS_DIR = os.path.join(_BASE_DIR, "workspace", "snapshots")
SNAPSHOTS_INDEX = os.path.join(SNAPSHOTS_DIR, "_index.json")


def _ensure_dir():
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


def _load_index() -> list:
    if not os.path.exists(SNAPSHOTS_INDEX):
        return []
    try:
        with open(SNAPSHOTS_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_index(index: list):
    with open(SNAPSHOTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def create_snapshot(path: str) -> str | None:
    """
    Tworzy migawkę pliku przed modyfikacją.
    Zwraca unikalny snapshot_id lub None jeśli plik nie istnieje.
    """
    if not os.path.isfile(path):
        return None

    _ensure_dir()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    basename = os.path.basename(path)
    snapshot_id = f"{timestamp}_{uuid.uuid4().hex[:8]}_{basename}"
    snapshot_path = os.path.join(SNAPSHOTS_DIR, snapshot_id + ".bak")

    try:
        shutil.copy2(path, snapshot_path)
    except Exception:
        return None

    # Zaktualizuj indeks
    index = _load_index()
    index.append({
        "id": snapshot_id,
        "original_path": os.path.abspath(path),
        "snapshot_path": snapshot_path,
        "created_at": datetime.now().isoformat(),
        "size_bytes": os.path.getsize(path),
    })
    # Trzymaj max 50 migawek
    if len(index) > 50:
        oldest = index.pop(0)
        try:
            os.remove(oldest["snapshot_path"])
        except Exception:
            pass
    _save_index(index)

    return snapshot_id


def list_snapshots() -> list:
    """Zwraca listę dostępnych migawek (od najnowszej)."""
    index = _load_index()
    return list(reversed(index))


def restore_snapshot(snapshot_id: str, target_path: str | None = None) -> tuple[bool, str]:
    """
    Przywraca plik ze migawki.
    Jeśli target_path jest None, przywraca do oryginalnej lokalizacji.
    Zwraca (success, message).
    """
    index = _load_index()
    entry = next((e for e in index if e["id"] == snapshot_id), None)

    if not entry:
        return False, f"Nie znaleziono migawki '{snapshot_id}'."

    snapshot_path = entry["snapshot_path"]
    if not os.path.exists(snapshot_path):
        return False, f"Plik migawki nie istnieje: {snapshot_path}"

    restore_to = target_path or entry["original_path"]
    if os.path.realpath(restore_to) != os.path.realpath(entry["original_path"]):
        return False, "Rollback do innej ścieżki niż oryginalna jest zablokowany."

    try:
        os.makedirs(os.path.dirname(os.path.abspath(restore_to)), exist_ok=True)
        shutil.copy2(snapshot_path, restore_to)
        return True, f"Przywrócono plik '{os.path.basename(restore_to)}' ze migawki {snapshot_id}."
    except Exception as e:
        return False, f"Błąd podczas przywracania: {str(e)}"


def delete_snapshot(snapshot_id: str) -> tuple[bool, str]:
    """Usuwa migawkę z dysku i indeksu."""
    index = _load_index()
    entry = next((e for e in index if e["id"] == snapshot_id), None)
    if not entry:
        return False, f"Nie znaleziono migawki '{snapshot_id}'."
    try:
        if os.path.exists(entry["snapshot_path"]):
            os.remove(entry["snapshot_path"])
        new_index = [e for e in index if e["id"] != snapshot_id]
        _save_index(new_index)
        return True, f"Usunięto migawkę {snapshot_id}."
    except Exception as e:
        return False, f"Błąd: {str(e)}"
