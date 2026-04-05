# DisciplineFuel Scheduler Setup
# Run this script once in PowerShell as Administrator

$batPath = "C:\Users\Admin\shorts\run_disciplinefuel.bat"
$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable

# Delete existing if any
foreach ($name in @("DisciplineFuel_Run1","DisciplineFuel_Run2","DisciplineFuel_Run3")) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}

# Create 3 daily triggers: 06:00, 13:00, 20:00
$times = @("06:00","13:00","20:00")
for ($i = 0; $i -lt $times.Count; $i++) {
    $trigger  = New-ScheduledTaskTrigger -Daily -At $times[$i]
    $taskName = "DisciplineFuel_Run$($i+1)"
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
    Write-Host "[OK] Scheduled $taskName at $($times[$i])"
}

Write-Host ""
Write-Host "Schedule created:"
Get-ScheduledTask -TaskName "DisciplineFuel_Run*" | Select-Object TaskName, State
