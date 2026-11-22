<#
  Mueve Alpha50 del PC a Figaro (servidor siempre encendido).

  Ejecutar en el PC, en PowerShell COMO ADMINISTRADOR (nssm lo necesita):
      cd C:\Users\Usuario\jarvis
      powershell -ExecutionPolicy Bypass -File deploy\alpha50_figaro\migrar_desde_pc.ps1

  Que hace:
    1. Comprueba SSH a Figaro y que el relay desplegado es el esperado.
    2. Para el servicio Alpha50Scheduler del PC (para no tener dos Alpha50).
    3. Sube codigo + datos (BD, plan, sesion de Garmin) + .env a Figaro y
       ejecuta deploy/alpha50_figaro/instalar.sh alli (systemd "alpha50").
    4. Si todo va bien: deja Alpha50Scheduler DESACTIVADO en el PC, pone
       ALPHA50_URL/ALPHA50_API_KEY en el .env del PC y reinicia JarvisAPI.
       Si falla: vuelve a arrancar Alpha50Scheduler en el PC (nada cambia).
  Se puede repetir: si Figaro ya tiene BD, no la pisa (solo actualiza codigo).
#>
param(
    [string]$Figaro    = "figaro",            # alias SSH (el mismo que usas con scp)
    [string]$JarvisDir = "C:\Users\Usuario\jarvis",
    [string]$FigaroIP  = "100.78.43.76",      # IP Tailscale de Figaro
    [int]   $Puerto    = 10050
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Paso($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Fallo($t) { Write-Host "ERROR: $t" -ForegroundColor Red; exit 1 }
function EscribirLF($ruta, $texto) {   # Linux necesita LF y sin BOM
    [IO.File]::WriteAllText($ruta, ($texto -replace "`r`n", "`n"), $utf8)
}

$esAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $esAdmin) { Fallo "Abre PowerShell como administrador (nssm lo necesita)." }

Set-Location $JarvisDir
$py   = Join-Path $JarvisDir ".venv\Scripts\python.exe"
$a50  = Join-Path $JarvisDir "alpha50"
$envPC = Join-Path $JarvisDir ".env"
foreach ($f in @($py, $envPC, "$a50\alpha50_cronologia.db", "$a50\alpha50_plan.json", "$a50\servicio.py")) {
    if (-not (Test-Path $f)) { Fallo "No encuentro $f (haz git pull primero)" }
}

# ---------------------------------------------------------------------------
Paso "1. Conexion con Figaro"
ssh -o BatchMode=yes -o ConnectTimeout=10 $Figaro "echo ok" | Out-Null
if ($LASTEXITCODE -ne 0) { Fallo "No hay SSH a '$Figaro' (Tailscale conectado? clave SSH?)" }

$stage = Join-Path $env:TEMP "alpha50_deploy"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path "$stage\codigo\alpha50", "$stage\codigo\connectors", "$stage\relay", "$stage\datos", "$stage\deploy" | Out-Null

try {
    # -----------------------------------------------------------------------
    Paso "2. Relay desplegado en Figaro"
    # Se sustituye relay.py: solo si el de Figaro es el ultimo conocido (o ya el nuevo).
    # (scp y git via Python: binario-seguro; la tuberia de PowerShell estropea las tildes)
    # 798f247 = relay.py que esta desplegado desde el 25/10 (antes de este cambio)
    $actual = "$stage\relay_figaro_actual.py"
    scp -q "${Figaro}:/opt/jarvis-relay/relay.py" $actual
    if ($LASTEXITCODE -ne 0) { Fallo "No pude leer /opt/jarvis-relay/relay.py de Figaro" }
    $cmp = & $py -c "import subprocess,sys; n=lambda b: b.replace(b'\r\n',b'\n').strip(); base=subprocess.run(['git','show','798f247:connectors/relay.py'],capture_output=True,check=True).stdout; a=n(open(sys.argv[1],'rb').read()); print('igual' if a in (n(base), n(open(sys.argv[2],'rb').read())) else 'distinto')" $actual "connectors\relay.py"
    if ($cmp -ne "igual") {
        Write-Host "El relay.py de Figaro tiene cambios que no estan en git:" -ForegroundColor Yellow
        git diff --no-index --stat connectors/relay.py $actual
        $r = Read-Host "Sobrescribirlo igualmente? (se guarda copia .bak en Figaro) [s/N]"
        if ($r -ne "s") { Fallo "Cancelado: sube primero esos cambios del relay a git." }
    } else { Write-Host "   relay.py de Figaro = version conocida" }

    # -----------------------------------------------------------------------
    Paso "3. Configuracion"
    $vals = @{}
    Get-Content $envPC | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $vals[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'") }
    }
    foreach ($k in @("GARMIN_EMAIL", "GARMIN_PASSWORD", "RELAY_API_KEY")) {
        if (-not $vals[$k]) { Fallo "Falta $k en $envPC" }
    }
    $clave = $vals["ALPHA50_API_KEY"]
    if (-not $clave) {
        $b = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
        $clave = -join ($b | ForEach-Object { $_.ToString("x2") })
    }
    $hora = if ($vals["ALPHA50_HORA"]) { $vals["ALPHA50_HORA"] } else { "07:00" }
    EscribirLF "$stage\env" (@(
        "GARMIN_EMAIL=$($vals['GARMIN_EMAIL'])",
        "GARMIN_PASSWORD=$($vals['GARMIN_PASSWORD'])",
        "RELAY_URL=http://127.0.0.1:10004",
        "RELAY_API_KEY=$($vals['RELAY_API_KEY'])",
        "ALPHA50_API_KEY=$clave",
        "ALPHA50_BIND=$FigaroIP",
        "ALPHA50_PORT=$Puerto",
        "ALPHA50_HORA=$hora"
    ) -join "`n")
    Write-Host "   .env de Figaro preparado (hora del brief: $hora)"

    # -----------------------------------------------------------------------
    Paso "4. Parar Alpha50 en el PC"
    nssm stop Alpha50Scheduler | Out-Null
    Start-Sleep -Seconds 3
    # Volcar el WAL a la BD para copiar un solo fichero coherente
    & $py -c "import sqlite3; c=sqlite3.connect(r'$a50\alpha50_cronologia.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close(); print('   BD consolidada')"

    # -----------------------------------------------------------------------
    Paso "5. Paquete"
    Get-ChildItem "$a50\*.py" | Where-Object { $_.Name -notlike "*_backup_*" } | Copy-Item -Destination "$stage\codigo\alpha50"
    Copy-Item "connectors\garmin_workouts.py" "$stage\codigo\connectors"
    Copy-Item "connectors\relay.py" "$stage\relay"
    Copy-Item "$a50\alpha50_cronologia.db" "$stage\datos"
    Get-ChildItem "$a50\*_plan.json" | Copy-Item -Destination "$stage\datos"
    if (Test-Path "$a50\.garmin_session") { Copy-Item "$a50\.garmin_session" "$stage\datos" -Recurse -Force }
    foreach ($f in @("instalar.sh", "alpha50.service", "requirements.txt")) {
        EscribirLF "$stage\deploy\$f" ([IO.File]::ReadAllText((Join-Path $JarvisDir "deploy\alpha50_figaro\$f")))
    }
    # Mismas versiones que el PC (la sesion guardada de Garmin depende de ellas)
    $lock = & $py -m pip freeze | Where-Object { $_ -match '^(garminconnect|garth|requests|schedule|python-dotenv)==' }
    EscribirLF "$stage\deploy\requirements.lock.txt" (($lock -join "`n") + "`n")
    Write-Host "   versiones: $($lock -join ', ')"

    # -----------------------------------------------------------------------
    Paso "6. Subir e instalar en Figaro"
    ssh $Figaro "rm -rf /tmp/alpha50_deploy"
    scp -r -q $stage "${Figaro}:/tmp/"
    if ($LASTEXITCODE -ne 0) { throw "scp fallo" }
    ssh -t $Figaro 'if [ "$(id -u)" = 0 ]; then bash /tmp/alpha50_deploy/deploy/instalar.sh; else sudo bash /tmp/alpha50_deploy/deploy/instalar.sh; fi'
    if ($LASTEXITCODE -ne 0) { throw "instalar.sh fallo en Figaro" }
    # Si el puerto pedido estaba ocupado, instalar.sh eligio otro: usar el real
    $real = (ssh $Figaro "cat /opt/alpha50/PUERTO" | Select-Object -First 1)
    if ($real -match '^\s*(\d+)\s*$') { $Puerto = [int]$matches[1] } else { throw "No pude leer el puerto de Alpha50 en Figaro" }
    Write-Host "   Alpha50 escucha en ${FigaroIP}:$Puerto"
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    Write-Host "Vuelvo a arrancar Alpha50 en el PC: todo sigue como estaba." -ForegroundColor Yellow
    nssm start Alpha50Scheduler | Out-Null
    exit 1
}
finally {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }   # lleva credenciales
}

# ---------------------------------------------------------------------------
Paso "7. Comprobar desde el PC"
$cab = @{ "X-Alpha50-Key" = $clave }
try {
    $h = Invoke-RestMethod "http://${FigaroIP}:$Puerto/historial?dias=3" -Headers $cab -TimeoutSec 15
    Write-Host "   Figaro responde. Nivel $($h.programa.nivel), semana $($h.programa.semana_plan)"
} catch {
    Write-Host "Figaro no responde desde el PC: $_" -ForegroundColor Red
    Write-Host "Vuelvo a arrancar Alpha50 en el PC. Revisa en Figaro: journalctl -u alpha50 -n 50" -ForegroundColor Yellow
    nssm start Alpha50Scheduler | Out-Null
    exit 1
}

# ---------------------------------------------------------------------------
Paso "8. Dejar el PC apuntando a Figaro"
nssm set Alpha50Scheduler Start SERVICE_DISABLED | Out-Null
Copy-Item $envPC "$envPC.bak.alpha50" -Force
$lineas = @(Get-Content $envPC | Where-Object { $_ -notmatch '^\s*ALPHA50_(URL|API_KEY)\s*=' })
$lineas += "ALPHA50_URL=http://${FigaroIP}:$Puerto"
$lineas += "ALPHA50_API_KEY=$clave"
[IO.File]::WriteAllLines($envPC, [string[]]$lineas, $utf8)   # sin BOM: pydantic lo leeria mal
nssm restart JarvisAPI | Out-Null
Write-Host "   Alpha50Scheduler del PC: parado y desactivado"
Write-Host "   .env del PC: ALPHA50_URL apunta a Figaro (copia en .env.bak.alpha50); JarvisAPI reiniciado"

Write-Host "`nLISTO. Alpha50 corre en Figaro (systemd 'alpha50')." -ForegroundColor Green
Write-Host "Prueba en Telegram:  /alpha50 estado"
Write-Host "Logs en Figaro:      ssh $Figaro journalctl -u alpha50 -f"
