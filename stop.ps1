# Stops this project's backend (app.serve) and frontend (vite) servers: the hidden ones start.ps1 launched, or any left over.
# Matched by command line, not port: Windows can report a listening port's owner as 0, which a port lookup can't kill.
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*$PSScriptRoot*" -and $_.CommandLine -match "app\.serve|vite|esbuild" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
