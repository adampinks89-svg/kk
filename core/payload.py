"""
core/payload.py – Ustrukturyzowany protokół payloadów JSON.

Każdy event wysyłany przez WebSocket ma pole `type`, które determinuje
jak frontend wyrenderuje wiadomość:
  - "thought"     → Panel Myśli (szary, kursywa, oddzielna sekcja)
  - "file_event"  → Dziennik Plików (kafelek z diff stats +N/-M)
  - "message"     → Główny Czat (tekst odpowiedzi, bloki kodu)
  - "approval_request" → Human-in-the-Loop modal z diffem
  - "system"      → Komunikat systemowy
  - "error"       → Błąd
  - "done"        → Koniec generowania
  - "loop_guard"  → Ostrzeżenie przed zapętleniem
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Literal, Optional, List


# ---------------------------------------------------------------------------
# Pomocnicze typy
# ---------------------------------------------------------------------------

EventType = Literal[
    "thought", "file_event", "message",
    "approval_request", "system", "error",
    "done", "loop_guard", "task_update"
]

FileOperation = Literal["read", "write", "create", "delete", "list"]


# ---------------------------------------------------------------------------
# Klasy payloadów
# ---------------------------------------------------------------------------

@dataclass
class ThoughtPayload:
    """Wewnętrzny monolog agenta – wyświetlany w Panelu Myśli."""
    text: str
    type: str = "thought"

    def to_dict(self) -> dict:
        return {"type": self.type, "text": self.text}


@dataclass
class DiffLine:
    """Pojedyncza linia diffu ('+', '-' lub ' ')."""
    op: Literal["+", "-", " "]   # dodana, usunięta, bez zmian
    content: str


@dataclass
class FileEventPayload:
    """Operacja plikowa agenta – wyświetlana w Dzienniku Plików."""
    operation: FileOperation
    path: str
    added: int = 0
    removed: int = 0
    diff_lines: List[dict] = field(default_factory=list)  # lista DiffLine jako dict
    snapshot_id: Optional[str] = None
    type: str = "file_event"

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "operation": self.operation,
            "path": self.path,
            "added": self.added,
            "removed": self.removed,
            "diff_lines": self.diff_lines,
            "snapshot_id": self.snapshot_id,
        }


@dataclass
class MessagePayload:
    """Właściwa treść odpowiedzi – wyświetlana w Głównym Czacie."""
    text: str
    tag: str = "agent"  # "agent", "code", "user", "tool"
    type: str = "message"

    def to_dict(self) -> dict:
        return {"type": self.type, "text": self.text, "tag": self.tag}


@dataclass
class ApprovalRequestPayload:
    """Human-in-the-Loop – żąda zatwierdzenia operacji przez użytkownika."""
    approval_id: str
    operation: FileOperation
    path: str
    diff_lines: List[dict]
    added: int = 0
    removed: int = 0
    snapshot_id: Optional[str] = None
    type: str = "approval_request"

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "approval_id": self.approval_id,
            "operation": self.operation,
            "path": self.path,
            "diff_lines": self.diff_lines,
            "added": self.added,
            "removed": self.removed,
            "snapshot_id": self.snapshot_id,
        }


@dataclass
class SystemPayload:
    """Komunikat systemowy."""
    text: str
    type: str = "system"

    def to_dict(self) -> dict:
        return {"type": self.type, "text": self.text}


@dataclass
class ErrorPayload:
    """Komunikat błędu."""
    text: str
    type: str = "error"

    def to_dict(self) -> dict:
        return {"type": self.type, "text": self.text}


@dataclass
class DonePayload:
    """Sygnał zakończenia generowania."""
    full_response: str = ""
    type: str = "done"

    def to_dict(self) -> dict:
        return {"type": self.type, "full_response": self.full_response}


@dataclass
class LoopGuardPayload:
    """Ostrzeżenie detektora zapętleń."""
    reason: str
    iteration: int
    type: str = "loop_guard"

    def to_dict(self) -> dict:
        return {"type": self.type, "reason": self.reason, "iteration": self.iteration}


@dataclass
class TaskUpdatePayload:
    """Aktualizacja listy zadań agenta (Task To-Do List)."""
    tasks: List[dict]   # lista {"id": str, "desc": str, "done": bool}
    type: str = "task_update"

    def to_dict(self) -> dict:
        return {"type": self.type, "tasks": self.tasks}
