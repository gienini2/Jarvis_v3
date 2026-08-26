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

# Modelo NO hardcodeado: se lee de config/providers.json (la misma fuente de verdad
# que usa el router de Jarvis). Asi, cuando Groq retira un modelo y se actualiza el
# JSON, este script lo sigue automaticamente y no vuelve a apuntar a uno muerto.
$providers = Join-Path $PSScriptRoot "..\config\providers.json"
$groqModel = & $venv -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(next(m['name'] for m in d['providers']['groq']['models'] if 'general' in m.get('roles',[])))" $providers 2>$null
if (-not $groqModel) { $groqModel = "openai/gpt-oss-120b" }   # fallback defensivo
$model = "groq/$groqModel"

Write-Host "Auditando: $Target" -ForegroundColor Cyan
Write-Host "Modelo: $model" -ForegroundColor DarkGray

& $venv -m aider `
    --model $model `
    --no-git `
    --yes `
    --message $message `
    --read $Target
