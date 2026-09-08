"""
backend/server.py – FastAPI backend z WebSocketami i Human-in-the-Loop.

Nowe funkcje:
  - Obsługa payloadów JSON (thought / file_event / message / approval_request / ...)
  - Kolejka oczekujących zatwierdzeń (pending_approvals)
  - Akcja WebSocket "approve" / "reject" dla Human-in-the-Loop
  - GET /api/snapshots  – lista dostępnych migawek
  - POST /api/rollback  – przywrócenie pliku ze migawki
"""
import os
import json
import asyncio
import threading
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.local_agent import check_ollama_status, query_local_model_stream
from core.logger import read_logs
from core.snapshot import list_snapshots, restore_snapshot
from core.security import ALLOWED_WORKSPACES, validate_path

app = FastAPI(title="Multi-Agent AI Studio Backend")

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

# ---------------------------------------------------------------------------
# Role agenta
# ---------------------------------------------------------------------------

ROLES = {
    "Domyślny Asystent": (
        "Jesteś pomocnym i inteligentnym asystentem AI. "
        "Myśl krok po kroku. Używaj znaczników <think>...</think> "
        "do wyrażania wewnętrznych przemyśleń przed odpowiedzią. "
        "BARDZO WAŻNE: Kiedy wywołasz jakiekolwiek narzędzie (tool call) i otrzymasz z powrotem wyniki, "
        "zawsze musisz napisać podsumowanie tych wyników dla użytkownika. Nigdy nie milcz po wykonaniu akcji!"
    ),
    "Doświadczony Programista": (
        "Jesteś ekspertem programowania (Senior Developer). "
        "Twoje odpowiedzi są zwięzłe, skupione na kodzie. "
        "Zawsze podajesz najlepsze praktyki i optymalizujesz rozwiązania. "
        "Używaj znaczników <think>...</think> do analizy problemu przed odpowiedzią. "
        "Przed modyfikacją pliku zawsze najpierw go odczytaj narzędziem read_file_tool. "
        "BARDZO WAŻNE: Po każdej modyfikacji (write_file_tool) lub odczycie musisz samodzielnie przeanalizować "
        "zwrócone wyniki i napisać krótkie podsumowanie lub kolejne kroki dla użytkownika. Nigdy nie kończ "
        "rozmowy bez napisania chociaż jednego zdania podsumowania statusu!"
    ),
    "Kreatywny Pisarz": (
        "Jesteś kreatywnym pisarzem i copywriterem. "
        "Używasz bogatego słownictwa, tworzysz wciągające treści."
    ),
}


# ---------------------------------------------------------------------------
# Endpointy HTTP
# ---------------------------------------------------------------------------

@app.get("/")
async def get_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Brak pliku index.html w folderze frontend</h1>")


@app.get("/api/status")
async def get_status():
    is_connected, models = check_ollama_status()
    return {"connected": is_connected, "models": models}


@app.get("/api/roles")
async def get_roles():
    return list(ROLES.keys())


@app.get("/api/workspaces")
async def get_workspaces():
    """Zwraca katalogi, w których agent może wykonywać operacje."""
    workspaces = []
    for root in ALLOWED_WORKSPACES:
        if not os.path.isdir(root):
            continue
        workspaces.append({"path": root, "name": os.path.basename(root) or root})
        for entry in sorted(os.scandir(root), key=lambda item: item.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                workspaces.append({"path": entry.path, "name": f"{os.path.basename(root)}/{entry.name}"})
    unique = {item["path"]: item for item in workspaces}
    return sorted(unique.values(), key=lambda item: item["path"])


@app.get("/api/logs")
async def get_logs():
    logs = read_logs(100)
    return {"logs": logs}


@app.get("/api/snapshots")
async def get_snapshots():
    """Zwraca listę dostępnych migawek plików (rollback)."""
    try:
        snapshots = list_snapshots()
        return {"snapshots": snapshots}
    except Exception as e:
        return {"snapshots": [], "error": str(e)}


class RollbackRequest(BaseModel):
    snapshot_id: str
    target_path: str | None = None


@app.post("/api/rollback")
async def do_rollback(req: RollbackRequest):
    """Przywraca plik ze wskazanej migawki."""
    success, message = restore_snapshot(req.snapshot_id, req.target_path)
    return {"success": success, "message": message}


# ---------------------------------------------------------------------------
# WebSocket / sesje
# ---------------------------------------------------------------------------

# stop_events: session_id → threading.Event
stop_events: Dict[str, threading.Event] = {}

# pending_approvals: session_id → {approval_id → {"event": Event, "approved": bool|None}}
pending_approvals_store: Dict[str, Dict[str, Any]] = {}


async def run_generator_in_thread(
    ws: WebSocket,
    messages: list,
    model: str,
    stop_event: threading.Event,
    pending_approvals: dict,
    working_directory: str,
):
    """
    Mostuje synchroniczny generator agenta do async WebSocket.
    Każdy yield z agenta to dict payload – wysyłany bezpośrednio jako JSON.
    """
    loop = asyncio.get_running_loop()
    iterator = query_local_model_stream(
        messages, model, stop_event, pending_approvals, working_directory=working_directory
    )
    full_response_parts = []

    try:
        while not stop_event.is_set():
            try:
                payload = await loop.run_in_executor(None, next, iterator)
            except StopIteration:
                break

            if payload == "[STREAM_EOF]" or stop_event.is_set():
                break

            # payload to dict – wysyłamy bezpośrednio
            if isinstance(payload, dict):
                # Zbierz tekst wiadomości do pełnej odpowiedzi
                if payload.get("type") == "message":
                    full_response_parts.append(payload.get("text", ""))

                try:
                    await ws.send_json(payload)
                except Exception:
                    break
            else:
                # Fallback: stary format string
                try:
                    await ws.send_json({"type": "message", "text": str(payload), "tag": "agent"})
                except Exception:
                    break

    except Exception as e:
        print(f"Błąd podczas generowania: {e}")

    if stop_event.is_set():
        try:
            await ws.send_json({
                "type": "system",
                "text": "\n[Przerwano przez użytkownika]\n"
            })
        except Exception:
            pass

    full_response = "".join(full_response_parts)
    messages.append({"role": "assistant", "content": full_response})

    try:
        await ws.send_json({"type": "done", "full_response": full_response})
    except Exception:
        pass


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    messages = []
    working_directory = ALLOWED_WORKSPACES[0]
    pending_approvals: Dict[str, Any] = {}
    pending_approvals_store[session_id] = pending_approvals

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            action = payload.get("action")

            # --- Ustawienie roli ---
            if action == "set_role":
                role = payload.get("role")
                system_prompt = ROLES.get(role, ROLES["Domyślny Asystent"])
                messages = [{"role": "system", "content": system_prompt}]
                await websocket.send_json({
                    "type": "system",
                    "text": f"\n--- Zmieniono rolę na: {role} ---\n"
                })

            # --- Ustawienie katalogu docelowego ---
            elif action == "set_workspace":
                requested_directory = payload.get("path", "")
                if validate_path(requested_directory) and os.path.isdir(requested_directory):
                    working_directory = os.path.abspath(requested_directory)
                    await websocket.send_json({
                        "type": "system",
                        "text": f"\n--- Katalog agenta: {working_directory} ---\n",
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "text": "Wybrany katalog nie jest dostępny w dozwolonym workspace.",
                    })

            # --- Czyszczenie kontekstu ---
            elif action == "clear":
                role = payload.get("role")
                system_prompt = ROLES.get(role, ROLES["Domyślny Asystent"])
                messages = [{"role": "system", "content": system_prompt}]
                await websocket.send_json({
                    "type": "system",
                    "text": "SYSTEM: Kontekst konwersacji został wyczyszczony.\n"
                })

            # --- Wiadomość użytkownika ---
            elif action == "message":
                msg = payload.get("message")
                model = payload.get("model")
                attachments = payload.get("attachments") or []

                user_message = {"role": "user", "content": msg or ""}
                image_data = [
                    item.get("data") for item in attachments
                    if item.get("type", "").startswith("image/") and item.get("data")
                ]
                if image_data:
                    user_message["images"] = image_data

                messages.append(user_message)
                stop_event = threading.Event()
                stop_events[session_id] = stop_event

                asyncio.create_task(
                    run_generator_in_thread(
                        websocket, messages, model, stop_event, pending_approvals,
                        working_directory,
                    )
                )

            # --- Stop ---
            elif action == "stop":
                if session_id in stop_events:
                    stop_events[session_id].set()

            # --- Human-in-the-Loop: zatwierdzenie ---
            elif action == "approve":
                approval_id = payload.get("approval_id")
                if approval_id and approval_id in pending_approvals:
                    pending_approvals[approval_id]["approved"] = True
                    pending_approvals[approval_id]["event"].set()
                    await websocket.send_json({
                        "type": "system",
                        "text": f"✅ Operacja {approval_id} zatwierdzona.\n"
                    })

            # --- Human-in-the-Loop: odrzucenie ---
            elif action == "reject":
                approval_id = payload.get("approval_id")
                if approval_id and approval_id in pending_approvals:
                    pending_approvals[approval_id]["approved"] = False
                    pending_approvals[approval_id]["event"].set()
                    await websocket.send_json({
                        "type": "system",
                        "text": f"⛔ Operacja {approval_id} odrzucona.\n"
                    })

    except WebSocketDisconnect:
        if session_id in stop_events:
            stop_events[session_id].set()
            del stop_events[session_id]
        pending_approvals_store.pop(session_id, None)
        # Odblokuj wszystkie oczekujące zatwierdzenia
        for entry in pending_approvals.values():
            entry["approved"] = False
            entry["event"].set()
