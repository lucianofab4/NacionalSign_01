# Backup do banco de dados Postgres
$backupDir = "C:\backup"
$timestamp = Get-Date -Format yyyyMMdd_HHmmss
$pgDumpPath = "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
$backupFile = "$backupDir\nacionalsign_$timestamp.backup"

& $pgDumpPath -U nacionalsign_user -h 127.0.0.1 -F c -b -v -f $backupFile nacionalsign

# Backup dos documentos e relatórios
Copy-Item -Recurse -Force C:\nacionalSign\backend\storage\documents "$backupDir\documents_$timestamp"
Copy-Item -Recurse -Force C:\nacionalSign\backend\storage\reports "$backupDir\reports_$timestamp"

Write-Host "Backup concluído em $timestamp."
