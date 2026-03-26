Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Solo Elderly Skill - Live Demo Menu"  -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [1] Sedentary / Isolation  (at-risk scenario)"
Write-Host "  [2] Positive Day           (goal-met scenario)"
Write-Host "  [3] Emergency Chest Pain   (critical scenario)"
Write-Host "  [4] Custom Input"
Write-Host "  [Q] Quit"
Write-Host ""

$choice = Read-Host "Select scenario (1/2/3/4/Q)"

switch ($choice) {
    "1" {
        Write-Host "`n--- Scenario: Sedentary / Isolation ---`n" -ForegroundColor Yellow
        python "$PSScriptRoot\demo_runner.py" `
            --memory-case sedentary_isolation `
            --location-case beijing_home `
            --user-input "I feel tired and did not go out this week. I do not have much appetite."
    }
    "2" {
        Write-Host "`n--- Scenario: Positive Day ---`n" -ForegroundColor Green
        python "$PSScriptRoot\demo_runner.py" `
            --memory-case positive_day `
            --location-case beijing_active `
            --user-input "I went to the store today and walked around the neighborhood."
    }
    "3" {
        Write-Host "`n--- Scenario: Emergency Chest Pain ---`n" -ForegroundColor Red
        python "$PSScriptRoot\demo_runner.py" `
            --memory-case emergency_chest_pain `
            --location-case beijing_emergency `
            --user-input "I have chest pain and feel very dizzy."
    }
    "4" {
        Write-Host ""
        $mem = Read-Host "Memory case (sedentary_isolation / positive_day / emergency_chest_pain)"
        $loc = Read-Host "Location case (beijing_home / beijing_active / beijing_emergency)"
        $msg = Read-Host "Patient says"
        Write-Host ""
        python "$PSScriptRoot\demo_runner.py" `
            --memory-case $mem `
            --location-case $loc `
            --user-input $msg
    }
    { $_ -eq "Q" -or $_ -eq "q" } {
        Write-Host "Bye!" -ForegroundColor Cyan
        exit
    }
    default {
        Write-Host "Invalid choice. Run the script again." -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "--- Demo complete ---" -ForegroundColor Cyan
Write-Host ""
