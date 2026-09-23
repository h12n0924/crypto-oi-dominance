param(
  [string]$From = '2021-12-01',
  [string]$To = '2022-08-31',
  [ValidateSet('um', 'cm', 'both')]
  [string]$Market = 'both',
  [int]$Workers = 16
)

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonPath = if ($pythonCommand) {
  $pythonCommand.Source
} else {
  Join-Path ([Environment]::GetFolderPath('UserProfile')) '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
  throw 'Python runtime not found. Install Python 3.11+ or update $pythonPath in this wrapper.'
}

& $pythonPath "$PSScriptRoot\binance-backfill.py" `
  '--from' $From `
  '--to' $To `
  '--market' $Market `
  '--workers' $Workers

exit $LASTEXITCODE
