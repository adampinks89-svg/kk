"""
core/rag_client.py – Klient zewnętrznej bazy wiedzy (RAG).

Odpytuje endpoint: POST /api/agent/context
z payload: {"query": "...", "context": "..."}

Zwraca zweryfikowane wzorce kodu, przykłady API, dokumentację.
Używany gdy:
  - linter wykryje błędy po zapisie pliku
  - agent zgłosi brak wiedzy o API/bibliotece
  - użytkownik jawnie poprosi o sprawdzenie
"""
import httpx
from core.logger import log_event, log_error

RAG_API_BASE = "https://ais-dev-dcea2b4uscqtl7gysisksn-340346620147.europe-west2.run.app"
RAG_CONTEXT_ENDPOINT = f"{RAG_API_BASE}/api/agent/context"

# Timeout dla zapytań do RAG (sekundy)
RAG_TIMEOUT = 10.0


def fetch_context(query: str, context: str = "") -> str:
    """
    Pobiera zweryfikowane wzorce z zewnętrznej bazy wiedzy.

    Args:
        query:   Pytanie lub opis problemu (np. "jak używać asyncio.gather?")
        context: Opcjonalny kontekst (np. treść błędu lintera)

    Returns:
        Tekst z odpowiedzią RAG lub komunikat o błędzie połączenia.
    """
    payload = {
        "query": query,
        "context": context,
    }

    log_event("RAG_REQUEST", "Odpytuję zewnętrzną bazę wiedzy", query[:200])

    try:
        with httpx.Client(timeout=RAG_TIMEOUT) as client:
            response = client.post(RAG_CONTEXT_ENDPOINT, json=payload)
            response.raise_for_status()
            data = response.json()

            # Obsługa różnych formatów odpowiedzi API
            if isinstance(data, dict):
                result = (
                    data.get("answer")
                    or data.get("context")
                    or data.get("result")
                    or data.get("content")
                    or str(data)
                )
            else:
                result = str(data)

            log_event("RAG_RESPONSE", "Otrzymano odpowiedź z bazy wiedzy", result[:300])
            return result

    except httpx.ConnectError:
        err = "⚠️ [RAG]: Brak połączenia z bazą wiedzy (ConnectError)."
        log_error("RAG_CONNECT_ERROR", Exception(err))
        return err
    except httpx.TimeoutException:
        err = "⚠️ [RAG]: Timeout połączenia z bazą wiedzy."
        log_error("RAG_TIMEOUT", Exception(err))
        return err
    except httpx.HTTPStatusError as e:
        err = f"⚠️ [RAG]: Błąd HTTP {e.response.status_code} z bazy wiedzy."
        log_error("RAG_HTTP_ERROR", e)
        return err
    except Exception as e:
        err = f"⚠️ [RAG]: Nieoczekiwany błąd: {str(e)}"
        log_error("RAG_UNKNOWN_ERROR", e)
        return err


def fetch_context_for_lint_errors(path: str, errors: list) -> str:
    """
    Specjalistyczne zapytanie RAG dla błędów lintera.

    Args:
        path:   Ścieżka do pliku z błędami
        errors: Lista błędów z run_linter()
    """
    if not errors:
        return ""

    error_summary = "\n".join(
        f"  Linia {e['line']} [{e['code']}]: {e['message']}"
        for e in errors[:5]  # max 5 błędów w zapytaniu
    )
    query = f"Błędy lintera w pliku '{path}':\n{error_summary}\nJak naprawić?"
    context = f"Plik: {path}\nBłędy:\n{error_summary}"

    return fetch_context(query, context)
