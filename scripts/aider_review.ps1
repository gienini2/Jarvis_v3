# aider_review.ps1 — Auditoría rápida con aider + Groq
# Uso: .\scripts\aider_review.ps1 <ruta_o_archivo>
# Ejemplo: .\scripts\aider_review.ps1 core\rag.py
#          .\scripts\aider_review.ps1 auditor\

param(
    [Parameter(Mandatory=$true)]
    [string]$Target
)

# Cargar variables de entorno desde .env
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}

if (-not $env:GROQ_API_KEY) {
    Write-Error "GROQ_API_KEY no encontrada en .env"
    exit 1
}

# Activar venv
$venv = Join-Path $PSScriptRoot "..\\.venv\\Scripts\\python.exe"
if (-not (Test-Path $venv)) {
    $venv = "python"
}

$message = "Revisa este codigo como arquitecto senior. Identifica: bugs, problemas de seguridad, codigo muerto, mejoras de rendimiento y deuda tecnica. Se directo y especifico con numero de linea."

Write-Host "Auditando: $Target" -ForegroundColor Cyan
Write-Host "Modelo: groq/llama-3.3-70b-versatile" -ForegroundColor DarkGray

& $venv -m aider `
    --model groq/llama-3.3-70b-versatile `
    --no-git `
    --yes `
    --message $message `
    --read $Target
