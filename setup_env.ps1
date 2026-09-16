# setup_env.ps1
# Run this script to set up environment variables for the Assistant

Write-Host "[ASSISTANT SETUP] Setting environment variables..." -ForegroundColor Cyan

# Set Picovoice Access Key
$env:PICOVOICE_ACCESS_KEY = "TBI+nigc5Pr8jyzQSI1ogmS2/qaytcOnd3zXWPRzBDK75H0xdYerYg=="

Write-Host "[ASSISTANT SETUP] ✓ PICOVOICE_ACCESS_KEY set for current session" -ForegroundColor Green
Write-Host ""
Write-Host "To make this permanent, add to your PowerShell profile or set as system environment variable:" -ForegroundColor Yellow
Write-Host "  1. Open System Properties → Advanced → Environment Variables" -ForegroundColor Yellow
Write-Host "  2. Add User Variable:" -ForegroundColor Yellow
Write-Host "     Name: PICOVOICE_ACCESS_KEY" -ForegroundColor Yellow
Write-Host "     Value: TBI+nigc5Pr8jyzQSI1ogmS2/qaytcOnd3zXWPRzBDK75H0xdYerYg==" -ForegroundColor Yellow
Write-Host ""
Write-Host "[ASSISTANT SETUP] You can now run: python assistant.py" -ForegroundColor Cyan
