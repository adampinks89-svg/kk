# Multi-Agent AI Studio

Lokalne studio dla agenta programistycznego z interfejsem webowym, wyborem modelu i roli, strumieniowaniem odpowiedzi, narzędziami do pracy z plikami oraz zatwierdzaniem zmian przez użytkownika.

## Wymagania

- Python 3.11 lub nowszy
- Ollama uruchomiona lokalnie, jeśli agent ma korzystać z modeli Ollama
- Model pobrany w Ollama, na przykład `ollama pull llama3.2`

## Instalacja

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

W systemie Windows aktywacja środowiska wygląda tak:

```powershell
.venv\Scripts\Activate.ps1
```

## Uruchomienie

```bash
python main.py
```

Następnie otwórz [http://127.0.0.1:8000](http://127.0.0.1:8000) w przeglądarce. Na Windows można również uruchomić `run_studio.bat`.

Serwer deweloperski działa z automatycznym przeładowaniem plików. Domyślnie nasłuchuje wyłącznie na `127.0.0.1`.

## Wybór folderu docelowego

W panelu bocznym pole **Folder docelowy** wskazuje katalog roboczy agenta. Kliknij ikonę folderu, aby otworzyć przeglądarkę katalogów:

1. wybierz podfolder, klikając jego nazwę;
2. użyj przycisku **Wyżej**, aby wrócić do katalogu nadrzędnego;
3. kliknij **Użyj tego folderu**, aby ustawić bieżący katalog agenta.

Agent używa wybranego katalogu dla poleceń, odczytu plików i modyfikacji. Dla bezpieczeństwa można wybierać wyłącznie katalogi znajdujące się wewnątrz obszarów określonych przez `ALLOWED_WORKSPACES` w `core/security.py`. Ukryte katalogi nie są prezentowane w przeglądarce.

## Najważniejsze endpointy

- `GET /api/status` - status Ollama i lista modeli;
- `GET /api/roles` - dostępne role agenta;
- `GET /api/workspaces` - początkowa lista workspace'ów;
- `GET /api/directories?path=...` - bieżący katalog i jego bezpośrednie podkatalogi;
- `GET /api/logs` - logi systemowe;
- `GET /api/snapshots` - dostępne migawki;
- `POST /api/rollback` - przywracanie pliku z migawki;
- `WS /ws/chat` - komunikacja z agentem.

## Testy

```bash
python -m pytest -q
```

Kontrola składni frontendu:

```bash
node --check frontend/app.js
```

## Struktura projektu

- `backend/server.py` - aplikacja FastAPI, endpointy HTTP i WebSocket;
- `agents/` - integracje agentów i obsługa modeli;
- `skills/` - rejestr oraz implementacje narzędzi agenta;
- `core/` - walidacja ścieżek, parser, linter, logowanie i migawki;
- `frontend/` - interfejs webowy;
- `tests/` - testy automatyczne.
