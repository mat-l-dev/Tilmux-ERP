# Arranca el ERP en tu PC y abre el navegador.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$puerto = 8000
$url = "http://127.0.0.1:$puerto"

Write-Host ""
Write-Host "  TILMUX ERP" -ForegroundColor Green
Write-Host "  Abriendo $url"
Write-Host "  Para detenerlo, cierra esta ventana o pulsa Ctrl+C."
Write-Host ""

# Abre el navegador cuatro segundos después, cuando el servidor ya escucha.
Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    "-NoProfile", "-Command", "Start-Sleep -Seconds 4; Start-Process '$url'"
) | Out-Null

uv run waitress-serve --listen="127.0.0.1:$puerto" config.wsgi:application
