# Detiene el servidor del ERP si esta corriendo.
$ErrorActionPreference = "SilentlyContinue"

$conexiones = Get-NetTCPConnection -LocalPort 8000 -State Listen
if (-not $conexiones) {
    Write-Host ""
    Write-Host "  El servidor no esta corriendo." -ForegroundColor Yellow
    Write-Host ""
    Start-Sleep -Seconds 2
    exit
}

foreach ($conexion in $conexiones) {
    $proceso = Get-Process -Id $conexion.OwningProcess
    if ($proceso) {
        Stop-Process -Id $proceso.Id -Force
        Write-Host ""
        Write-Host "  Servidor detenido (PID $($proceso.Id), $($proceso.ProcessName))." -ForegroundColor Green
        Write-Host ""
    }
}

Start-Sleep -Seconds 2
