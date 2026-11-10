# Starts the backend (:8000) and frontend (:5173) in hidden windows, then opens the app in the browser.
# Anything already listening on those ports is stopped first, so running it again restarts both.
# Stop both with stop.ps1. A desktop shortcut runs:  powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File <this file>

& "$PSScriptRoot\stop.ps1"
$env:PYTHONIOENCODING = "utf-8"
Start-Process "$PSScriptRoot\backend\venv\Scripts\python.exe" "-m app.serve --port 8000" -WorkingDirectory "$PSScriptRoot\backend" -WindowStyle Hidden
Start-Process "npm.cmd" "run dev" -WorkingDirectory "$PSScriptRoot\frontend" -WindowStyle Hidden

# open the browser once the frontend answers (up to ~30 s)
for ($i = 0; $i -lt 30; $i++) {
  try { Invoke-WebRequest http://localhost:5173 -UseBasicParsing -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep 1 }
}
Start-Process http://localhost:5173
