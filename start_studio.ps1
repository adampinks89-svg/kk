$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# Jawny tryb hosta: agent pracuje przez PowerShell na Windowsie.
$env:KK_WINDOWS_HOST = '1'

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Nie znaleziono polecenia python w PATH.'
}

python .\main.py
