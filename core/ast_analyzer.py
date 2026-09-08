"""
core/ast_analyzer.py – Analiza struktury kodu przez Abstract Syntax Tree.

Zamiast podawać agentowi surowy tekst kodu (co prowadzi do halucynacji
o nieistniejących metodach), podajemy mapę:
  - klasy i ich metody
  - funkcje na poziomie modułu
  - importy
  - stałe i zmienne globalne

Pozwala to agentowi na precyzyjne odwołania do istniejących API.
"""
import ast
import os
import json
from typing import Optional


def _extract_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Buduje czytelny podpis funkcji/metody z argumentami."""
    args = []
    # Normalne argumenty
    all_args = node.args
    defaults_offset = len(all_args.args) - len(all_args.defaults)

    for i, arg in enumerate(all_args.args):
        name = arg.arg
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        default_idx = i - defaults_offset
        default = ast.unparse(all_args.defaults[default_idx]) if default_idx >= 0 else None

        part = name
        if ann:
            part += f": {ann}"
        if default:
            part += f" = {default}"
        args.append(part)

    # *args
    if all_args.vararg:
        args.append(f"*{all_args.vararg.arg}")
    # **kwargs
    if all_args.kwarg:
        args.append(f"**{all_args.kwarg.arg}")

    return_ann = ""
    if node.returns:
        return_ann = f" -> {ast.unparse(node.returns)}"

    return f"({', '.join(args)}){return_ann}"


def _get_docstring(node) -> Optional[str]:
    """Wyodrębnia docstring z node'a (jeśli istnieje)."""
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)):
        return node.body[0].value.value.strip().split("\n")[0]  # tylko pierwsza linia
    return None


def get_ast_context(path: str) -> str:
    """
    Parsuje plik Python przez AST i zwraca JSON z mapą struktury kodu.

    Returns:
        JSON string z kluczami: imports, globals, functions, classes
        Lub komunikat błędu jeśli plik nie jest prawidłowym Pythonem.
    """
    if not os.path.isfile(path):
        return json.dumps({"error": f"Plik nie istnieje: {path}"})

    if not path.endswith(".py"):
        return json.dumps({"error": "AST działa tylko na plikach .py"})

    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        return json.dumps({"error": f"Nie można odczytać pliku: {str(e)}"})

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        return json.dumps({"error": f"Błąd składni: {str(e)}"})

    result = {
        "file": os.path.basename(path),
        "imports": [],
        "globals": [],
        "functions": [],
        "classes": [],
    }

    for node in ast.walk(tree):
        # Importy
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                result["imports"].append(f"{module}.{alias.asname or alias.name}")

    # Tylko wierzchni poziom (bez zagnieżdżonych)
    for node in tree.body:
        # Zmienne globalne / stałe
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result["globals"].append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            result["globals"].append(node.target.id)

        # Funkcje na poziomie modułu
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _extract_signature(node)
            doc = _get_docstring(node)
            entry = {
                "name": node.name,
                "signature": sig,
                "line": node.lineno,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
            if doc:
                entry["docstring"] = doc
            result["functions"].append(entry)

        # Klasy
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            class_doc = _get_docstring(node)
            methods = []

            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = _extract_signature(item)
                    method_doc = _get_docstring(item)
                    method_entry = {
                        "name": item.name,
                        "signature": sig,
                        "line": item.lineno,
                        "is_async": isinstance(item, ast.AsyncFunctionDef),
                    }
                    if method_doc:
                        method_entry["docstring"] = method_doc
                    methods.append(method_entry)

            class_entry = {
                "name": node.name,
                "bases": bases,
                "line": node.lineno,
                "methods": methods,
            }
            if class_doc:
                class_entry["docstring"] = class_doc
            result["classes"].append(class_entry)

    return json.dumps(result, indent=2, ensure_ascii=False)


def get_ast_summary(path: str) -> str:
    """Zwraca skróconą, czytelną mapę struktury pliku (dla agenta)."""
    raw = get_ast_context(path)
    try:
        data = json.loads(raw)
    except Exception:
        return raw

    if "error" in data:
        return f"[AST Error] {data['error']}"

    lines = [f"[AST] Struktura pliku: {data['file']}"]

    if data.get("imports"):
        # Pokaz max 10 importow
        shown = data["imports"][:10]
        lines.append(f"  Importy: {', '.join(shown)}" +
                     (f" (+{len(data['imports'])-10} wiecej)" if len(data["imports"]) > 10 else ""))

    if data.get("globals"):
        lines.append(f"  Zmienne globalne: {', '.join(data['globals'][:8])}")

    for fn in data.get("functions", []):
        prefix = "async " if fn.get("is_async") else ""
        doc = f" # {fn['docstring']}" if fn.get("docstring") else ""
        lines.append(f"  def {prefix}{fn['name']}{fn['signature']}{doc}")

    for cls in data.get("classes", []):
        bases_str = f"({', '.join(cls['bases'])})" if cls.get("bases") else ""
        doc = f" # {cls['docstring']}" if cls.get("docstring") else ""
        lines.append(f"  class {cls['name']}{bases_str}{doc}")
        for m in cls.get("methods", []):
            prefix = "async " if m.get("is_async") else ""
            m_doc = f" # {m['docstring']}" if m.get("docstring") else ""
            lines.append(f"      def {prefix}{m['name']}{m['signature']}{m_doc}")

    return "\n".join(lines)
