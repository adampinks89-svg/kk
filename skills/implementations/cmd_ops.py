"""
skills/implementations/cmd_ops.py – Narzędzie wykonywania poleceń/skryptów.
"""
import os
import json
import subprocess
from core.security import sanitize_command, validate_path

def run_command_tool(command: str, cwd: str = ".") -> str:
    """
    Wykonuje bezpieczne polecenie w powłoce systemowej (np. uruchamia skrypt Python).
    """
    if not cwd or cwd == ".":
        cwd = os.getcwd()

    if not validate_path(cwd):
        return json.dumps({
            "success": False,
            "error": f"Katalog roboczy '{cwd}' wykracza poza dozwolony obszar."
        })

    if not sanitize_command(command):
        return json.dumps({
            "success": False,
            "error": "Polecenie zawiera niedozwolone instrukcje systemowe."
        })

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return json.dumps({
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({
            "success": False,
            "error": "Przekroczono limit czasu wykonania polecenia (30s)."
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Błąd uruchamiania polecenia: {str(e)}"
        })
