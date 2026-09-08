"""Wielowarstwowa analiza statyczna kodu po zapisie pliku.

Dla Pythona łączymy trzy niezależne perspektywy:
* Ruff: błędy stylu, jakości i typowych bugów,
* mypy: niespójności typów,
* Bandit: znane ryzykowne wzorce bezpieczeństwa.

Narzędzia są opcjonalne. Gdy nie ma żadnego z nich, zostaje wbudowana
weryfikacja składni przez ``py_compile``. Wynik zachowuje dotychczasowy
format, aby agent i RAG nie wymagały zmian kontraktu.
"""
import os
import json
import py_compile
import re
import subprocess
from typing import List


LintError = dict  # {"line": int, "col": int, "code": str, "message": str}

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css",
    ".go", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs",
}


def _run_ruff(path: str) -> List[LintError] | None:
    """Uruchamia Ruff w stabilnym formacie JSON."""
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", "--exit-zero", path],
            capture_output=True, text=True, timeout=15
        )
        raw = json.loads(result.stdout or "[]")
        return [
            {
                "line": item.get("location", {}).get("row", 0),
                "col": item.get("location", {}).get("column", 0),
                "code": item.get("code", "RUFF"),
                "message": item.get("message", ""),
                "source": "ruff",
            }
            for item in raw
        ]
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_mypy(path: str) -> List[LintError] | None:
    """Uruchamia mypy i parsuje błędy typów bez zależności od koloru terminala."""
    try:
        result = subprocess.run(
            [
                "mypy", "--no-incremental", "--ignore-missing-imports",
                "--follow-imports=skip", "--show-error-codes", "--no-error-summary", path,
            ],
            capture_output=True, text=True, timeout=15
        )
        errors = []
        for line in result.stdout.splitlines():
            match = re.match(r"^.+:(\d+)(?::(\d+))?: (error|warning|note): (.*)$", line)
            if match:
                try:
                    line_no, col_no, severity, message = match.groups()
                    code_match = re.search(r"\s\[([^]]+)\]$", message)
                    errors.append({
                        "line": int(line_no),
                        "col": int(col_no or 0),
                        "code": f"MYPY[{code_match.group(1)}]" if code_match else "MYPY",
                        "message": f"{severity}: {message}",
                        "source": "mypy",
                    })
                except (TypeError, ValueError):
                    pass
        return errors
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_bandit(path: str) -> List[LintError] | None:
    """Uruchamia Bandit w JSON i mapuje ostrzeżenia bezpieczeństwa."""
    try:
        result = subprocess.run(
            ["bandit", "-q", "-f", "json", path],
            capture_output=True, text=True, timeout=15
        )
        raw = json.loads(result.stdout or '{"results": []}')
        return [
            {
                "line": item.get("line_number", 0),
                "col": 0,
                "code": item.get("test_id", "BANDIT"),
                "message": f"{item.get('issue_text', '')} ({item.get('issue_severity', 'UNKNOWN')})",
                "source": "bandit",
            }
            for item in raw.get("results", [])
        ]
    except FileNotFoundError:
        return None


def _run_eslint(path: str) -> List[LintError] | None:
    """Uruchamia ESLint dla JavaScriptu/TypeScriptu, jeśli jest zainstalowany."""
    try:
        result = subprocess.run(
            ["eslint", "--format", "json", path],
            capture_output=True, text=True, timeout=20,
        )
        raw = json.loads(result.stdout or "[]")
        errors = []
        for file_result in raw:
            for item in file_result.get("messages", []):
                errors.append({
                    "line": item.get("line", 0),
                    "col": item.get("column", 0),
                    "code": item.get("ruleId") or "ESLINT",
                    "message": item.get("message", ""),
                    "source": "eslint",
                })
        return errors
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_stylelint(path: str) -> List[LintError] | None:
    """Uruchamia Stylelint dla CSS, jeśli jest zainstalowany."""
    try:
        result = subprocess.run(
            ["stylelint", "--formatter", "json", path],
            capture_output=True, text=True, timeout=20,
        )
        raw = json.loads(result.stdout or "[]")
        errors = []
        for file_result in raw:
            for item in file_result.get("warnings", []):
                errors.append({
                    "line": item.get("line", 0),
                    "col": item.get("column", 0),
                    "code": item.get("rule", "STYLELINT"),
                    "message": item.get("text", ""),
                    "source": "stylelint",
                })
        return errors
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_htmlhint(path: str) -> List[LintError] | None:
    """Uruchamia HTMLHint dla HTML, jeśli jest zainstalowany."""
    try:
        result = subprocess.run(
            ["htmlhint", "-f", "json", path],
            capture_output=True, text=True, timeout=20,
        )
        raw = json.loads(result.stdout or "[]")
        return [
            {
                "line": item.get("line", 0),
                "col": item.get("col", 0),
                "code": item.get("message", "HTMLHINT"),
                "message": item.get("message", ""),
                "source": "htmlhint",
            }
            for item in raw
        ]
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_gofmt(path: str) -> List[LintError] | None:
    """Sprawdza formatowanie Go przy pomocy oficjalnego gofmt."""
    try:
        result = subprocess.run(
            ["gofmt", "-d", path], capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            errors = []
            pattern = re.compile(r"^.*:(\d+):(\d+): (.*)$")
            for line in result.stderr.splitlines():
                match = pattern.match(line)
                if match:
                    line_no, col_no, message = match.groups()
                    errors.append({
                        "line": int(line_no),
                        "col": int(col_no),
                        "code": "GOFMT-SYNTAX",
                        "message": message,
                        "source": "gofmt",
                    })
            return errors
        if not result.stdout:
            return []
        line_match = re.search(r"@@ -([0-9]+)", result.stdout)
        return [{
            "line": int(line_match.group(1)) if line_match else 0,
            "col": 0,
            "code": "GOFMT",
            "message": "Plik nie jest sformatowany przez gofmt.",
            "source": "gofmt",
        }]
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_cpp_syntax(path: str) -> List[LintError] | None:
    """Sprawdza składnię C/C++ bez linkowania programu."""
    try:
        extension = os.path.splitext(path)[1].lower()
        compiler = "g++" if extension in {".cc", ".cpp", ".cxx", ".hpp"} else "gcc"
        language = "c++" if compiler == "g++" else "c"
        result = subprocess.run(
            [compiler, "-fsyntax-only", "-x", language, path],
            capture_output=True, text=True, timeout=20,
        )
        errors = []
        pattern = re.compile(r"^.*:(\d+):(\d+): (error|warning): (.*)$")
        for line in result.stderr.splitlines():
            match = pattern.match(line)
            if match:
                line_no, col_no, severity, message = match.groups()
                errors.append({
                    "line": int(line_no),
                    "col": int(col_no),
                    "code": f"{compiler.upper()}-{severity.upper()}",
                    "message": message,
                    "source": compiler,
                })
        return errors
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _run_csharp(path: str) -> List[LintError] | None:
    """Uruchamia dotnet build, gdy plik należy do projektu C#."""
    project_dir = os.path.dirname(os.path.abspath(path))
    project = next((name for name in os.listdir(project_dir) if name.endswith(".csproj")), None)
    if not project:
        return None
    try:
        result = subprocess.run(
            ["dotnet", "build", os.path.join(project_dir, project), "--no-restore", "-v", "q"],
            capture_output=True, text=True, timeout=30,
        )
        errors = []
        pattern = re.compile(r"^(.+?)\((\d+),(\d+)\): (error|warning) ([A-Z0-9]+): (.*)$")
        for line in result.stdout.splitlines():
            match = pattern.match(line.strip())
            if match:
                _, line_no, col_no, severity, code, message = match.groups()
                errors.append({
                    "line": int(line_no),
                    "col": int(col_no),
                    "code": code,
                    "message": f"{severity}: {message}",
                    "source": "dotnet",
                })
        return errors
    except FileNotFoundError:
        return None
    except Exception:
        return None
    except Exception:
        return None


def _run_py_compile(path: str) -> List[LintError]:
    """Fallback: sprawdza tylko składnię Pythona (wbudowany moduł)."""
    try:
        py_compile.compile(path, doraise=True)
        return []
    except py_compile.PyCompileError as e:
        # Format: "  File "<path>", line N\n    <code>\n..."
        msg = str(e)
        line_num = 0
        try:
            import re
            m = re.search(r"line (\d+)", msg)
            if m:
                line_num = int(m.group(1))
        except Exception:
            pass
        return [{"line": line_num, "col": 0, "code": "SyntaxError", "message": msg}]


def run_linter(path: str) -> List[LintError]:
    """
    Uruchamia analizę statyczną pliku. Dla Pythona agreguje Ruff, mypy i Bandit.
    Zwraca listę błędów (pusta = brak problemów).
    Obsługuje Python, JavaScript/TypeScript, HTML, CSS, Go, C/C++ i C#.
    """
    extension = os.path.splitext(path)[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        return []
    if not os.path.isfile(path):
        return []

    analyzers = {
        ".py": (_run_ruff, _run_mypy, _run_bandit),
        ".js": (_run_eslint,), ".jsx": (_run_eslint,),
        ".ts": (_run_eslint,), ".tsx": (_run_eslint,),
        ".html": (_run_htmlhint,), ".htm": (_run_htmlhint,),
        ".css": (_run_stylelint,), ".go": (_run_gofmt,),
        ".c": (_run_cpp_syntax,), ".h": (_run_cpp_syntax,),
        ".cc": (_run_cpp_syntax,), ".cpp": (_run_cpp_syntax,),
        ".cxx": (_run_cpp_syntax,), ".hpp": (_run_cpp_syntax,),
        ".cs": (_run_csharp,),
    }
    errors = []
    analyzers_available = False
    for analyzer in analyzers[extension]:
        result = analyzer(path)
        if result is not None:
            analyzers_available = True
            errors.extend(result)

    if not analyzers_available and extension == ".py":
        return _run_py_compile(path)

    errors.sort(key=lambda item: (item["line"], item["col"], item.get("source", "")))
    return errors


def format_lint_errors(errors: List[LintError]) -> str:
    """Formatuje listę błędów jako czytelny tekst dla agenta."""
    if not errors:
        return "✅ Brak błędów składniowych ani lintingowych."
    lines = [f"⚠️ Znaleziono {len(errors)} błąd(ów) lintera:"]
    for e in errors:
        source = f"/{e['source']}" if e.get("source") else ""
        lines.append(f"  Linia {e['line']}, kol {e['col']} [{e['code']}{source}]: {e['message']}")
    return "\n".join(lines)
