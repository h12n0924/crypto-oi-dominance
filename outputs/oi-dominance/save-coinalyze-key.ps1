$ErrorActionPreference = 'Stop'
$credentialDir = Join-Path $env:LOCALAPPDATA 'OI-Dominance'
$credentialPath = Join-Path $credentialDir 'coinalyze-key.dpapi'

New-Item -ItemType Directory -Path $credentialDir -Force | Out-Null
$secureKey = Read-Host 'Coinalyze API key (stored with Windows DPAPI for this user only)' -AsSecureString
$secureKey | ConvertFrom-SecureString | Set-Content -LiteralPath $credentialPath -Encoding ASCII

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = New-Object Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object Security.AccessControl.FileSystemAccessRule(
  $currentIdentity,
  [Security.AccessControl.FileSystemRights]::FullControl,
  [Security.AccessControl.AccessControlType]::Allow
)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $credentialPath -AclObject $acl

Write-Output "Encrypted credential saved for $currentIdentity at $credentialPath"
