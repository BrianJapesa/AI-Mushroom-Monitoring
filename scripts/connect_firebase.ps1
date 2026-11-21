$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$secretDirectory = Join-Path $root 'backend\secrets'
$secretFile = Join-Path $secretDirectory 'serviceAccountKey.json'
$envFile = Join-Path $root 'backend\.env'

Write-Host 'Choose the Firebase service-account JSON file you downloaded from the client-owned Firebase project.'
Add-Type -AssemblyName System.Windows.Forms
$picker = New-Object System.Windows.Forms.OpenFileDialog
$picker.Title = 'Select the Firebase service-account JSON file'
$picker.Filter = 'Firebase key file (*.json)|*.json'
$picker.Multiselect = $false
if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Host 'No file selected. Nothing was changed.'
    exit 1
}

try {
    $keyInfo = Get-Content -LiteralPath $picker.FileName -Raw | ConvertFrom-Json -ErrorAction Stop
    if ($keyInfo.type -ne 'service_account' -or -not $keyInfo.private_key -or -not $keyInfo.client_email) {
        throw 'That file does not look like a Firebase service-account key.'
    }
} catch {
    Write-Host 'That file could not be validated as a Firebase service-account key. Download the JSON key again from Firebase Project settings > Service accounts.' -ForegroundColor Red
    exit 1
}

$databaseUrl = Read-Host 'Paste the Realtime Database URL shown in Firebase'
if ($databaseUrl -notmatch '^https://[A-Za-z0-9.-]+/?$') {
    Write-Host 'That URL does not look right. Copy the full HTTPS Realtime Database URL from the Firebase console.' -ForegroundColor Red
    exit 1
}
$databaseUrl = $databaseUrl.TrimEnd('/')

New-Item -ItemType Directory -Force -Path $secretDirectory | Out-Null
if (Test-Path -LiteralPath $envFile) {
    $backupName = 'backend\.env.backup.' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    Copy-Item -LiteralPath $envFile -Destination (Join-Path $root $backupName)
}
Copy-Item -LiteralPath $picker.FileName -Destination $secretFile -Force
$envContents = @"
# Local Firebase presentation settings. Keep this file private.
DB_BACKEND=firebase
FIREBASE_URL=$databaseUrl
FIREBASE_CREDENTIALS=backend/secrets/serviceAccountKey.json
"@
$tempFile = "$envFile.tmp"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($tempFile, $envContents, $utf8)
Move-Item -LiteralPath $tempFile -Destination $envFile -Force

$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$aclFailed = $false
& icacls $secretDirectory /inheritance:r /grant:r ("{0}:(OI)(CI)F" -f $currentIdentity) | Out-Null
if ($LASTEXITCODE -ne 0) { $aclFailed = $true }
& icacls $envFile /inheritance:r /grant:r ("{0}:F" -f $currentIdentity) | Out-Null
if ($LASTEXITCODE -ne 0) { $aclFailed = $true }
& icacls $secretFile /inheritance:r /grant:r ("{0}:F" -f $currentIdentity) | Out-Null
if ($LASTEXITCODE -ne 0) { $aclFailed = $true }
if ($aclFailed) {
    Write-Host 'Firebase files were saved, but Windows could not restrict their access. Ask a trusted Windows administrator to check the file permissions.' -ForegroundColor Red
    exit 1
}
Write-Host 'Firebase settings saved on this computer. The service key was not displayed.' -ForegroundColor Green
Write-Host 'Next, run scripts\prototype.ps1 to show Firebase-backed demo data in the dashboard.'

