# Rota JARVIS_API_KEY sin mostrarla nunca en pantalla.
# Ejecutar en PowerShell NORMAL (no administrador):
#   powershell -ExecutionPolicy Bypass -File scripts\rotar_clave.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
$adb = "C:\Users\Usuario\android-tools\platform-tools\adb.exe"
$face = "https://pc-supermolon.taild7b9e6.ts.net"

function New-Key([int]$len = 32) {
    $alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $limit = 256 - (256 % $alphabet.Length)
    $buf = New-Object byte[] 1
    $sb = New-Object System.Text.StringBuilder
    while ($sb.Length -lt $len) {
        $rng.GetBytes($buf)
        if ($buf[0] -lt $limit) { [void]$sb.Append($alphabet[$buf[0] % $alphabet.Length]) }
    }
    $sb.ToString()
}

function Status-Of([string]$url, [hashtable]$headers) {
    try { (Invoke-WebRequest -Uri $url -Headers $headers -UseBasicParsing -TimeoutSec 15).StatusCode }
    catch { if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "sin respuesta" } }
}

if (-not (Test-Path $envPath)) { throw "No encuentro $envPath" }
if ((Read-Host "Esto cambia la clave de la API de Jarvis. Escribe SI para continuar") -ne "SI") { return }

$text = [IO.File]::ReadAllText($envPath)
if ($text -notmatch "(?m)^JARVIS_API_KEY=") { throw "El .env no tiene la linea JARVIS_API_KEY=" }

$backupDir = Join-Path $env:USERPROFILE ".jarvis-env-backup"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$backup = Join-Path $backupDir (".env." + (Get-Date -Format "yyyyMMdd-HHmmss"))
Copy-Item $envPath $backup
Write-Host "1/6 Copia del .env anterior en $backup (borrala cuando todo funcione)"

$key = New-Key 32
$updated = [regex]::Replace($text, "(?m)^JARVIS_API_KEY=[^\r\n]*", "JARVIS_API_KEY=$key")
[IO.File]::WriteAllText($envPath, $updated, (New-Object System.Text.UTF8Encoding $false))
Write-Host "2/6 Clave nueva escrita en .env (no se muestra)"

$phoneFile = $false
if (Test-Path $adb) {
    $devices = (& $adb devices) -match "`tdevice$"
    if ($devices) {
        $tmp = Join-Path $env:TEMP "jarvis-k.txt"
        [IO.File]::WriteAllText($tmp, $key)
        & $adb push $tmp /sdcard/Download/jarvis-clave.txt | Out-Null
        Remove-Item $tmp -Force
        $phoneFile = $true
        Write-Host "3/6 Clave copiada al movil: Descargas/jarvis-clave.txt (abrela, copia el texto y pegalo en la cara)"
    }
}
if (-not $phoneFile) { Write-Host "3/6 Movil no conectado por USB: tendras que teclear la clave en la cara" }

if ((Read-Host "4/6 Actualizar el relay de Figaro por SSH ahora? (s/n)") -eq "s") {
    $remote = "sed -i 's/^JARVIS_API_KEY=.*/JARVIS_API_KEY=$key/' /opt/jarvis-relay/.env && systemctl restart jarvis-relay && echo relay-actualizado"
    & ssh -i (Join-Path $HOME ".ssh\figaro_jarvis") root@100.78.43.76 $remote
} else {
    Write-Host "   Pendiente: poner la misma clave en /opt/jarvis-relay/.env (JARVIS_API_KEY) y reiniciar jarvis-relay"
}

Write-Host "5/6 Reiniciando JarvisAPI (acepta el aviso de administrador)"
$nssm = (Get-Command nssm -ErrorAction Stop).Source
Start-Process -FilePath $nssm -ArgumentList "restart", "JarvisAPI" -Verb RunAs -Wait
Start-Sleep -Seconds 8

$withKey = Status-Of "$face/history" @{ "X-Jarvis-Key" = $key }
$noKey = Status-Of "$face/history" @{}
Write-Host "6/6 Comprobacion: con la clave nueva -> $withKey (esperado 200) | sin clave -> $noKey (esperado 401)"

if ($phoneFile) {
    Read-Host "Cuando hayas pegado la clave en el movil, pulsa Enter para borrar el archivo del movil"
    & $adb shell rm /sdcard/Download/jarvis-clave.txt
    Write-Host "Archivo de clave borrado del movil"
}
Remove-Variable key, updated, text

Write-Host ""
Write-Host "Quedan por actualizar a mano (usan la clave vieja y daran 401):"
Write-Host " - clientes externos como OpenClaw (cabecera X-Jarvis-Key)"
Write-Host " - cualquier otro equipo con una copia del .env"
