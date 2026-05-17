# Tax Calculator - Uninstaller
# PowerShell Uninstaller Script

Write-Host "===========================================" -ForegroundColor Red
Write-Host "        Tax Calculator Uninstaller         " -ForegroundColor Red
Write-Host "===========================================" -ForegroundColor Red
Write-Host ""

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$installPath = $null
$registryPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator"

if ($isAdmin -and (Test-Path $registryPath)) {
    try {
        $installPath = (Get-ItemProperty -Path $registryPath -Name "InstallLocation" -ErrorAction Stop).InstallLocation
        if ($installPath) {
            Write-Host "Found via registry: $installPath" -ForegroundColor Green
        }
    } catch {
        $installPath = $null
    }
}

if (-not $installPath) {
    $possiblePaths = @(
        "$env:LOCALAPPDATA\TaxCalculator",
        "${env:ProgramFiles}\TaxCalculator",
        "${env:ProgramFiles(x86)}\TaxCalculator"
    )

    foreach ($path in $possiblePaths) {
        if (Test-Path "$path\tax_app.exe") {
            $installPath = $path
            Write-Host "Found in standard location: $installPath" -ForegroundColor Green
            break
        }
    }
}

if (-not $installPath) {
    Write-Host "Application not found automatically." -ForegroundColor Yellow
    $manualPath = Read-Host "Enter the full path to the installation folder"
    if ($manualPath -and (Test-Path "$manualPath\tax_app.exe")) {
        $installPath = $manualPath
    }
}

if (-not $installPath) {
    Write-Host "Tax Calculator not found on this system." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Installation found at: $installPath" -ForegroundColor Cyan
Write-Host ""

$confirm = Read-Host "Do you really want to remove Tax Calculator? (y/N)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Uninstallation cancelled" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 0
}

try {
    $process = Get-Process -Name "tax_app" -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "Stopping running application..." -ForegroundColor Yellow
        $process | Stop-Process -Force
        Start-Sleep -Seconds 2
    }

    Write-Host "Removing shortcuts..." -ForegroundColor Cyan

    $desktopShortcuts = @(
        "$([Environment]::GetFolderPath('Desktop'))\Tax Calculator.lnk",
        "$([Environment]::GetFolderPath('Desktop'))\Калькулятор ТН.lnk"
    )
    foreach ($shortcut in $desktopShortcuts) {
        if (Test-Path $shortcut) {
            Remove-Item $shortcut -Force -ErrorAction SilentlyContinue
        }
    }

    $startMenuShortcuts = @(
        "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Tax Calculator.lnk",
        "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Калькулятор ТН.lnk"
    )
    foreach ($shortcut in $startMenuShortcuts) {
        if (Test-Path $shortcut) {
            Remove-Item $shortcut -Force -ErrorAction SilentlyContinue
        }
    }

    if ($isAdmin -and (Test-Path $registryPath)) {
        try {
            Remove-Item -Path $registryPath -Force
            Write-Host "Registry entry removed" -ForegroundColor Green
        } catch {
            Write-Host "Could not remove registry entry: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    $uninstallInfo = Join-Path $installPath "uninstall.ini"
    if (Test-Path $uninstallInfo) {
        Remove-Item $uninstallInfo -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Removing application files..." -ForegroundColor Cyan
    Remove-Item -Path $installPath -Recurse -Force -ErrorAction Stop
    Write-Host "Application files removed" -ForegroundColor Green

    Write-Host ""
    Write-Host "===========================================" -ForegroundColor Green
    Write-Host "UNINSTALLATION COMPLETED SUCCESSFULLY!" -ForegroundColor Green
    Write-Host "===========================================" -ForegroundColor Green
} catch {
    Write-Host "Error during uninstallation: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Try running uninstaller as administrator" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Read-Host "Press Enter to exit"
