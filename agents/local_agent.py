"""
agents/local_agent.py – Pętla agentowa ReAct z zabezpieczeniami.

Nowe funkcje:
  - Loop Guard: limit iteracji narzędzi (domyślnie MAX_TOOL_ITERATIONS = 15)
  - Detektor oscylacji: wykrywa gdy agent wywołuje te same narzędzia z tymi samymi
    argumentami w kółko (okno = OSCILLATION_WINDOW = 3 ostatnich wywołań)
  - Task To-Do List: wewnętrzny rejestr celów agenta (przekazywany w system prompt)
  - Payloady JSON: thought / file_event / message / loop_guard
  - Human-in-the-Loop: emit approval_request dla operacji zapisu zamiast
    natychmiastowego zapisu (decyzja zarządzana przez server.py)
"""
import os
import json
import ollama
import httpx
from urllib.parse import urlsplit
from skills.registry import OLLAMA_TOOLS, execute_tool
from core.logger import log_event, log_error
from core.payload import (
    ThoughtPayload, FileEventPayload, MessagePayload,
    LoopGuardPayload, SystemPayload, ErrorPayload
)

# ---------------------------------------------------------------------------
# Konfiguracja
# ---------------------------------------------------------------------------
MAX_TOOL_ITERATIONS = 15   # Limit narzędzi w jednej sesji
OSCILLATION_WINDOW = 3     # Okno detekcji oscylacji (ostatnie N wywołań)


def _normalize_ollama_host(value: str | None) -> str:
    """Normalizuje adres klienta; adres nasłuchiwania 0.0.0.0 zastępuje loopbackiem."""
    host_value = (value or "http://localhost:11434").strip()
    if "://" not in host_value:
        host_value = f"http://{host_value}"

    parsed = urlsplit(host_value)
    if parsed.hostname in {"0.0.0.0", "::", "::0"}:
        return f"{parsed.scheme or 'http'}://127.0.0.1:{parsed.port or 11434}"
    return host_value.rstrip("/")


OLLAMA_HOST = _normalize_ollama_host(os.getenv("OLLAMA_HOST"))

ollama_client = ollama.Client(host=OLLAMA_HOST, timeout=None)


# ---------------------------------------------------------------------------
# Status Ollama
# ---------------------------------------------------------------------------

def check_ollama_status():
    """Sprawdza serwer Ollama i zwraca krotkę (is_connected, models)."""
    models = []
    is_connected = False

    try:
        models_info = ollama_client.list()
        is_connected = True

        if hasattr(models_info, "models"):
            raw_models = models_info.models
        elif isinstance(models_info, dict):
            raw_models = models_info.get("models", [])
        else:
            raw_models = []

        for m in raw_models:
            if not m:
                continue
            if hasattr(m, "model") and m.model:
                models.append(m.model)
            elif hasattr(m, "name") and m.name:
                models.append(m.name)
            elif isinstance(m, dict):
                name = m.get("model") or m.get("name")
                if name:
                    models.append(name)
    except Exception as e:
        log_error("check_ollama_status_library_failed", e)

    if not is_connected or not models:
        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.get(f"{OLLAMA_HOST}/api/tags")
                if response.status_code == 200:
                    is_connected = True
                    data = response.json()
                    for m in data.get("models", []):
                        name = m.get("name") or m.get("model")
                        if name:
                            models.append(name)
        except Exception as http_err:
            log_error("check_ollama_status_http_failed", http_err)

    if not is_connected:
        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{OLLAMA_HOST}/")
                if res.status_code == 200:
                    is_connected = True
        except Exception:
            is_connected = False

    if is_connected and not models:
        models = ["Brak modeli w Ollama"]

    return is_connected, models


# ---------------------------------------------------------------------------
# Detektor oscylacji
# ---------------------------------------------------------------------------

class OscillationDetector:
    """
    Wykrywa, gdy agent wielokrotnie wywołuje to samo narzędzie
    z identycznymi argumentami w ciągu OSCILLATION_WINDOW kroków.
    """
    def __init__(self, window: int = OSCILLATION_WINDOW):
        self.window = window
        self.history: list[tuple[str, str]] = []  # (tool_name, args_hash)

    def record(self, tool_name: str, args: dict) -> bool:
        """
        Zapisuje wywołanie i sprawdza oscylację.
        Zwraca True jeśli wykryto oscylację.
        """
        args_key = json.dumps(args, sort_keys=True)
        call_sig = (tool_name, args_key)
        self.history.append(call_sig)

        if len(self.history) > self.window * 2:
            self.history = self.history[-(self.window * 2):]

        if len(self.history) >= self.window:
            last_n = self.history[-self.window:]
            if len(set(last_n)) == 1:
                return True  # Wszystkie ostatnie N wywołań są identyczne

        return False

    def reset(self):
        self.history.clear()


# ---------------------------------------------------------------------------
# Główna pętla agentowa
# ---------------------------------------------------------------------------

def query_local_model_stream(
    messages: list,
    model_name: str,
    stop_event=None,
    pending_approvals: dict | None = None,
    task_list: list | None = None,
    _oscillation: OscillationDetector | None = None,
    _tool_iteration: int = 0,
):
    """
    Strumieniuje odpowiedź z Ollama jako dict payloady JSON.

    Yieldy payloady jako słowniki:
      {"type": "thought", "text": "..."}
      {"type": "file_event", "operation": "write", "path": "...", "added": N, ...}
      {"type": "message", "text": "...", "tag": "agent"}
      {"type": "approval_request", "approval_id": "...", ...}
      {"type": "loop_guard", "reason": "...", "iteration": N}
      "[STREAM_EOF]"   ← string-sentinel zamiast StopIteration

    Args:
        messages:          Historia konwersacji
        model_name:        Nazwa modelu Ollama
        stop_event:        threading.Event do przerywania
        pending_approvals: Słownik {approval_id: asyncio.Event} zarządzany przez server.py
        task_list:         Lista zadań agenta [{"id": str, "desc": str, "done": bool}]
    """
    if not model_name or model_name in [
        "Brak modeli", "Brak modeli w Ollama", "Szukanie modeli..."
    ]:
        yield ErrorPayload(
            "Wybierz poprawny model z listy po lewej stronie."
        ).to_dict()
        yield "[STREAM_EOF]"
        return

    oscillation = _oscillation or OscillationDetector()
    tool_iteration = _tool_iteration

    try:
        response = ollama_client.chat(
            model=model_name,
            messages=messages,
            stream=True,
            tools=OLLAMA_TOOLS,
            options={"num_ctx": 16384},
        )

        tool_calls = []
        text_buffer = ""
        in_think = False

        try:
            for chunk in response:
                if stop_event and stop_event.is_set():
                    break

                if "message" not in chunk:
                    continue

                msg = chunk["message"]

                # Zbierz tool_calls
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        tool_calls.append(tc)

                # Strumieniuj tekst
                content = msg.get("content", "")
                if not content:
                    continue

                text_buffer += content

                # Parsuj <think> tagi inline
                while text_buffer:
                    if not in_think:
                        idx = text_buffer.find("<think>")
                        if idx != -1:
                            if idx > 0:
                                yield MessagePayload(text_buffer[:idx]).to_dict()
                            yield ThoughtPayload("").to_dict()  # nagłówek
                            in_think = True
                            text_buffer = text_buffer[idx + 7:]
                            continue
                        # Bezpieczne przepisanie jeśli nie ma partial match
                        partial = any(
                            text_buffer.endswith("<think>"[:i])
                            for i in range(1, 7)
                        )
                        if not partial:
                            yield MessagePayload(text_buffer).to_dict()
                            text_buffer = ""
                        else:
                            break
                    else:
                        idx = text_buffer.find("</think>")
                        if idx != -1:
                            if idx > 0:
                                yield ThoughtPayload(text_buffer[:idx]).to_dict()
                            in_think = False
                            text_buffer = text_buffer[idx + 8:]
                            continue
                        partial = any(
                            text_buffer.endswith("</think>"[:i])
                            for i in range(1, 8)
                        )
                        if not partial:
                            yield ThoughtPayload(text_buffer).to_dict()
                            text_buffer = ""
                        else:
                            break

        except Exception as stream_err:
            log_error("STREAM_ITERATION_ERROR", stream_err)
            yield ErrorPayload(f"Strumień przerwany: {stream_err}").to_dict()
            yield "[STREAM_EOF]"
            return

        # Opróżnij bufor po zakończeniu strumienia
        if text_buffer:
            if in_think:
                yield ThoughtPayload(text_buffer).to_dict()
            else:
                yield MessagePayload(text_buffer).to_dict()

        # -----------------------------------------------------------------
        # Obsługa wywołań narzędzi
        # -----------------------------------------------------------------
        if tool_calls:
            guard_triggered = False
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                if stop_event and stop_event.is_set():
                    break

                func_name = tc["function"]["name"]
                args = tc["function"]["arguments"]

                # --- Loop Guard: limit iteracji ---
                tool_iteration += 1
                if tool_iteration > MAX_TOOL_ITERATIONS:
                    guard_triggered = True
                    payload = LoopGuardPayload(
                        reason=f"Przekroczono limit {MAX_TOOL_ITERATIONS} wywołań narzędzi w jednej sesji.",
                        iteration=tool_iteration,
                    ).to_dict()
                    yield payload
                    log_event("LOOP_GUARD", "Limit iteracji osiągnięty", str(tool_iteration))
                    break

                # --- Detektor oscylacji ---
                if oscillation.record(func_name, args):
                    guard_triggered = True
                    payload = LoopGuardPayload(
                        reason=(
                            f"Wykryto oscylację: narzędzie '{func_name}' wywoływane "
                            f"{OSCILLATION_WINDOW} razy z identycznymi argumentami."
                        ),
                        iteration=tool_iteration,
                    ).to_dict()
                    yield payload
                    log_event("OSCILLATION_DETECTED", f"Narzędzie: {func_name}", json.dumps(args))
                    break

                # --- Blokada plików binarnych przy odczycie ---
                if func_name == "read_file_tool" and "path" in args:
                    path_lower = args["path"].lower()
                    if path_lower.endswith((".db", ".sqlite", ".sqlite3", ".exe", ".bin")):
                        file_name = os.path.basename(args["path"])
                        yield ErrorPayload(
                            f"Blokada: Odmowa odczytu pliku binarnego '{file_name}'."
                        ).to_dict()
                        result_str = f"Błąd: Plik '{file_name}' jest binarny."
                        messages.append({
                            "role": "tool", "content": result_str, "name": func_name
                        })
                        continue

                # --- Human-in-the-Loop dla operacji zapisu ---
                is_write_op = func_name == "write_file_tool"
                approval_id = None

                if is_write_op and pending_approvals is not None:
                    import uuid
                    import threading

                    approval_id = str(uuid.uuid4())[:8]
                    approval_event = threading.Event()
                    pending_approvals[approval_id] = {
                        "event": approval_event,
                        "approved": None,
                    }

                    # Wylicz diff przed zapisem (preview)
                    path = args.get("path", "")
                    new_content = args.get("content", "")
                    old_content = ""
                    if os.path.isfile(path):
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                old_content = f.read()
                        except Exception:
                            pass

                    from skills.implementations.file_ops import _compute_diff
                    diff_data = _compute_diff(
                        old_content, new_content, os.path.basename(path)
                    )

                    # Emituj żądanie zatwierdzenia
                    from core.payload import ApprovalRequestPayload
                    yield ApprovalRequestPayload(
                        approval_id=approval_id,
                        operation="write",
                        path=path,
                        diff_lines=diff_data["diff_lines"],
                        added=diff_data["added"],
                        removed=diff_data["removed"],
                    ).to_dict()

                    # Czekaj na decyzję użytkownika (max 120 sekund)
                    approval_event.wait(timeout=120)

                    decision = pending_approvals.pop(approval_id, {})
                    if not decision.get("approved", False):
                        yield SystemPayload(
                            f"⛔ Operacja zapisu '{os.path.basename(path)}' odrzucona przez użytkownika."
                        ).to_dict()
                        result_str = "Operacja odrzucona przez użytkownika."
                        messages.append({
                            "role": "tool", "content": result_str, "name": func_name
                        })
                        log_event("HITL_REJECTED", f"Odrzucono zapis: {path}", "")
                        continue

                    log_event("HITL_APPROVED", f"Zatwierdzono zapis: {path}", "")

                # --- Wykonaj narzędzie ---
                yield SystemPayload(f"🛠️ Wykonuję: **`{func_name}`**...").to_dict()

                try:
                    result_str = execute_tool(func_name, args)
                except Exception as tool_err:
                    result_str = f"Błąd narzędzia: {str(tool_err)}"

                log_event("TOOL_CALL", f"Agent użył {func_name}", str(args))
                log_event(
                    "TOOL_RESULT", f"Wynik {func_name}",
                    result_str[:500] + ("..." if len(result_str) > 500 else "")
                )

                # --- Przetwórz wynik i emituj file_event ---
                if func_name in ("write_file_tool", "read_file_tool", "list_dir_tool"):
                    try:
                        result_data = json.loads(result_str)
                        if func_name == "write_file_tool" and result_data.get("success"):
                            yield FileEventPayload(
                                operation=result_data.get("operation", "write"),
                                path=result_data.get("path", args.get("path", "")),
                                added=result_data.get("added", 0),
                                removed=result_data.get("removed", 0),
                                diff_lines=result_data.get("diff_lines", []),
                                snapshot_id=result_data.get("snapshot_id"),
                            ).to_dict()
                            # Ostrzegaj o błędach lintera
                            if result_data.get("lint_message"):
                                yield SystemPayload(result_data["lint_message"]).to_dict()
                        elif func_name == "read_file_tool" and result_data.get("success"):
                            yield FileEventPayload(
                                operation="read",
                                path=result_data.get("path", ""),
                                added=0,
                                removed=0,
                            ).to_dict()
                    except (json.JSONDecodeError, TypeError):
                        pass

                messages.append({
                    "role": "tool",
                    "content": result_str,
                    "name": func_name,
                })

            # Wygeneruj kolejną odpowiedź po wykonaniu narzędzi (pętla zamiast rekurencji)
            if not (stop_event and stop_event.is_set()) and not guard_triggered:
                yield SystemPayload(f"📥 Zwrócono wynik narzędzi").to_dict()
                yield from query_local_model_stream(
                    messages,
                    model_name,
                    stop_event,
                    pending_approvals,
                    task_list,
                    oscillation,
                    tool_iteration,
                )
                return

    except Exception as e:
        log_error("query_local_model_stream_global_failed", e)
        yield ErrorPayload(f"Inicjalizacja nieudana: {e}").to_dict()

    yield "[STREAM_EOF]"
