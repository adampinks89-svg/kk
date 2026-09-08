import os
import datetime
import traceback

LOG_FILE = os.path.abspath("agent_system.log")

def log_event(event_type: str, message: str, details: str = ""):
    """Zapisuje zdarzenie do pliku logu agenta."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_entry = f"[{timestamp}] [{event_type.upper()}] {message}\n"
    if details:
        log_entry += f"Szczegóły:\n{details}\n"
    log_entry += "-" * 40 + "\n"

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Błąd podczas zapisu logu: {e}")

def log_error(context: str, error: Exception):
    """Loguje wyjątek Pythona ze stosem wywołań."""
    tb = traceback.format_exc()
    log_event("ERROR", f"Błąd w: {context}", tb)

def read_logs(lines: int = 50) -> str:
    """Odczytuje ostatnie X linii z logu."""
    if not os.path.exists(LOG_FILE):
        return "Brak pliku logów."

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        if not all_lines:
            return "Logi są puste."

        recent_lines = all_lines[-lines:]
        return "".join(recent_lines)
    except Exception as e:
        return f"Błąd podczas odczytu logów: {e}"
