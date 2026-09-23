param(
  [string]$From = (Get-Date).AddYears(-2).ToString('yyyy-MM-dd'),
  [string]$To = (Get-Date).ToString('yyyy-MM-dd')
)

$secureKey = Read-Host 'Coinalyze API key' -AsSecureString
$apiKeyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

try {
  $env:COINALYZE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($apiKeyPtr)
  node "$PSScriptRoot\oi-dominance.mjs" "--from=$From" "--to=$To"
} finally {
  Remove-Item Env:COINALYZE_API_KEY -ErrorAction SilentlyContinue
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($apiKeyPtr)
}
