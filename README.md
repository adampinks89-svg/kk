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

## Tryb Windows i PowerShell

`run_studio.bat` uruchamia `start_studio.ps1`, który ustawia `KK_WINDOWS_HOST=1` i startuje aplikację bezpośrednio na Windowsie. W tym trybie narzędzie `run_command_tool` wykonuje polecenia przez PowerShell, pokazuje komendę, wyjście, błąd, kod zakończenia i aktualny katalog w czacie. Wynik błędnej komendy trafia również do historii narzędzi, więc model może go automatycznie przeanalizować i zaproponować kolejną próbę.

Tryb hosta daje agentowi dostęp do dowolnych istniejących plików i katalogów użytkownika. Włączaj go tylko lokalnie i świadomie: polecenia modelu mogą wykonywać operacje systemowe z uprawnieniami konta uruchamiającego aplikację. W środowisku deweloperskim bez Windowsa zmienna nie uruchamia PowerShell i pozostaje używany sandbox Docker.

Polecenia `cd` i `Set-Location` są utrzymywane między wywołaniami: po każdej komendzie agent dostaje aktualny katalog roboczy. Przycisk 📁 pozwala również wskazać folder bezpośrednio w interfejsie.

Domyślnie agent nie widzi plików tego projektu. Aby udostępnić jeden lub kilka zewnętrznych katalogów roboczych, ustaw `KK_WORKSPACE_ROOTS`, rozdzielając ścieżki separatorem systemowym. Przykłady:

```bash
KK_WORKSPACE_ROOTS=/home/user/Folder4:/home/user/AnotherProject python main.py
```

W PowerShell:

```powershell
$env:KK_WORKSPACE_ROOTS = "D:\Folder4;D:\AnotherProject"
python main.py
```

Bez `KK_WORKSPACE_ROOTS` agent startuje w `Downloads` bieżącego użytkownika. Jeśli ten katalog nie istnieje, używany jest katalog domowy użytkownika. Przycisk 📁 pozwala następnie zmienić `target_dir` bez restartu aplikacji.

Korzenie systemu i katalogi systemowe nie mogą zostać ustawione jako workspace agenta. Rollback przywraca snapshot wyłącznie do oryginalnej ścieżki pliku.

Filetree w panelu bocznym pokazuje pliki wybranego workspace'u i dobiera ikonę na podstawie rozszerzenia. Katalogi projektu aplikacji są filtrowane również po stronie narzędzi agenta.

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
- `GET /api/directory-roots` - korzenie dysków dostępne w przeglądarce folderów;
- `GET /api/filetree?path=...` - pliki i podkatalogi wybranego workspace'u;
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
