"""Opcjonalny backend agenta oparty o Google ADK i Google Gen AI SDK."""
import os
from typing import Any

from skills.registry import SKILL_FUNCTIONS

try:
    from google.adk.agents import Agent
except ImportError:  # Pakiety Google są opcjonalne dla trybu Ollama.
    Agent = None


GOOGLE_MODEL_PREFIX = "gemini:"
DEFAULT_GOOGLE_MODEL = "gemini-2.5-flash"


def is_available() -> bool:
    """Zwraca True, gdy ADK jest zainstalowany i skonfigurowano klucz API."""
    return Agent is not None and bool(os.getenv("GOOGLE_API_KEY"))


def available_model() -> str | None:
    """Zwraca model Google w formacie używanym przez interfejs aplikacji."""
    if not is_available():
        return None
    model = os.getenv("GOOGLE_MODEL", DEFAULT_GOOGLE_MODEL)
    return f"{GOOGLE_MODEL_PREFIX}{model}"


def model_name(model: str | None) -> str:
    """Usuwa prefiks dostawcy z nazwy modelu przekazanej przez UI."""
    if model and model.startswith(GOOGLE_MODEL_PREFIX):
        return model[len(GOOGLE_MODEL_PREFIX):]
    return model or os.getenv("GOOGLE_MODEL", DEFAULT_GOOGLE_MODEL)


def create_agent(instruction: str | None = None) -> Any:
    """Tworzy agenta ADK z narzędziami już dostępnymi w projekcie."""
    if Agent is None:
        raise RuntimeError(
            "Google ADK nie jest zainstalowany. Uruchom: pip install -r requirements.txt"
        )
    if not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("Brak GOOGLE_API_KEY dla backendu Google ADK.")

    return Agent(
        name="multi_agent_studio",
        model=model_name(os.getenv("GOOGLE_MODEL")),
        description="Agent programistyczny Multi-Agent Studio",
        instruction=instruction or (
            "Jesteś pomocnym agentem programistycznym. Najpierw analizuj stan projektu, "
            "przed zapisem odczytaj plik, a po zmianie uruchom odpowiednią walidację."
        ),
        tools=list(SKILL_FUNCTIONS.values()),
    )