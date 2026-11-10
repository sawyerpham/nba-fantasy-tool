# Stops whatever is listening on the backend (8000) and frontend (5173) ports: the hidden servers start.ps1 launched.
foreach ($port in 8000, 5173) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
