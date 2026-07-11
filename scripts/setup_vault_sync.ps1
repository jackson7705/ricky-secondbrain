# Setup Windows Task Scheduler for Vault Git Sync
# Run this script as Administrator

$TaskName = "SecondBrain-VaultSync"
$TaskPath = Join-Path $PSScriptRoot "run_vault_sync.vbs"
$Description = "Second Brain - Git vault sync every 2 minutes"

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Task '$TaskName' already exists. Removing old task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the action
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument """$TaskPath""" `
    -WorkingDirectory $PSScriptRoot

# Create triggers - Daily at midnight repeating every 2 minutes all day
# (AtLogOn with repetition breaks after sleep/wake on Windows)
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$repetition = (New-ScheduledTaskTrigger -Once -At "00:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition
$dailyTrigger.Repetition = $repetition

# Also trigger at logon for immediate start (single run, no repetition needed)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$triggers = @($dailyTrigger, $logonTrigger)

# Create settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

# Create principal (run as current user)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description $Description

Write-Host ""
Write-Host "Task '$TaskName' created successfully!"
Write-Host ""
Write-Host "To verify: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "To run now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To disable: Disable-ScheduledTask -TaskName '$TaskName'"
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName'"
