# Tax Calculator - Uninstaller
# PowerShell Uninstaller Script

Write-Host "===========================================" -ForegroundColor Red
Write-Host "        Tax Calculator Uninstaller       " -ForegroundColor Red
Write-Host "===========================================" -ForegroundColor Red
Write-Host ""

# Search for installed version - simplified approach
Write-Host "Searching for Tax Calculator installation..."

$installPath = $null

# Quick search in standard locations first
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

if (-not $installPath) {
    Write-Host "Not found in standard locations. Searching all drives..."
    Write-Host "This may take a minute..."

    $drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name.Length -eq 1 }

    foreach ($drive in $drives) {
        try {
            Write-Host "Scanning drive $($drive.Name): ..." -NoNewline
            $foundFiles = Get-ChildItem -Path "$($drive.Name):\" -Filter "tax_app.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue
            if ($foundFiles) {
                $file = $foundFiles | Select-Object -First 1
                $candidatePath = Split-Path $file.FullName -Parent
                $installPath = $candidatePath
                Write-Host "FOUND at $installPath" -ForegroundColor Green
                break
            } else {
                Write-Host "not found"
            }
        } catch {
            Write-Host "access error"
        }
    }
}

if (-not $installPath) {
    Write-Host "Tax Calculator not found on this system." -ForegroundColor Red
    Write-Host "The application may not be installed, or you may need to run this as administrator." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

$installPath = $null

if ($uninstallIniFiles) {
    foreach ($iniFile in $uninstallIniFiles) {
        try {
            $content = Get-Content $iniFile.FullName -Raw -ErrorAction SilentlyContinue
            if ($content -match "InstallPath=(.+)") {
                $candidatePath = $Matches[1].Trim()
                if (Test-Path "$candidatePath\tax_app.exe") {
                    $installPath = $candidatePath
                    Write-Host "Found via uninstall.ini: $installPath" -ForegroundColor Cyan
                    break
                }
            }
        } catch {
            continue
        }
    }
}

# Fallback: search in standard locations
if (-not $installPath) {
    $possiblePaths = @(
        "$env:LOCALAPPDATA\TaxCalculator",
        "${env:ProgramFiles}\TaxCalculator",
        "${env:ProgramFiles(x86)}\TaxCalculator"
    )

    foreach ($path in $possiblePaths) {
        if (Test-Path "$path\tax_app.exe") {
            $installPath = $path
            Write-Host "Found in standard location: $installPath" -ForegroundColor Cyan
            break
        }
    }
}

# Last resort: search all drives for tax_app.exe
if (-not $installPath) {
    Write-Host "Searching all drives for Tax Calculator..." -ForegroundColor Yellow
    $drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name.Length -eq 1 -and $_.Name -ne "C" } # Skip C: since we already searched it deeply

    foreach ($drive in $drives) {
        try {
            Write-Host "Searching drive $($drive.Name):..." -NoNewline
            $foundFiles = Get-ChildItem -Path "$($drive.Name):\" -Filter "tax_app.exe" -Recurse -Depth 3 -ErrorAction SilentlyContinue
            if ($foundFiles) {
                foreach ($file in $foundFiles) {
                    $candidatePath = Split-Path $file.FullName -Parent
                    $installPath = $candidatePath
                    Write-Host "Found on drive $($drive.Name): $installPath" -ForegroundColor Green
                    break
                }
            } else {
                Write-Host " not found"
            }
            if ($installPath) { break }
        } catch {
            Write-Host " error: $($_.Exception.Message)"
        }
    }

    # Also search for any folder containing tax_app.exe (even without TaxCalculator in name)
    if (-not $installPath) {
        Write-Host "Deep search for tax_app.exe on all drives..." -ForegroundColor Yellow
        foreach ($drive in $drives) {
            try {
                $foundFiles = Get-ChildItem -Path "$($drive.Name):\" -Filter "tax_app.exe" -Recurse -ErrorAction SilentlyContinue
                if ($foundFiles) {
                    $file = $foundFiles | Select-Object -First 1
                    $candidatePath = Split-Path $file.FullName -Parent
                    $installPath = $candidatePath
                    Write-Host "Found tax_app.exe on drive $($drive.Name): $installPath" -ForegroundColor Green
                    break
                }
            } catch {
                continue
            }
        }
    }
}

if (-not $installPath) {
    Write-Host "Application not found on this computer" -ForegroundColor Red
    Write-Host "Please check if Tax Calculator is installed" -ForegroundColor Yellow
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
    # Stop process if running
    $process = Get-Process -Name "tax_app" -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "Stopping running application..." -ForegroundColor Yellow
        $process | Stop-Process -Force
        Start-Sleep -Seconds 2
    }

    # Remove shortcuts
    Write-Host "Removing shortcuts..." -ForegroundColor Cyan

    $desktopShortcut = "$([Environment]::GetFolderPath('Desktop'))\Tax Calculator.lnk"
    if (Test-Path $desktopShortcut) {
        Remove-Item $desktopShortcut -Force
        Write-Host "Desktop shortcut removed" -ForegroundColor Green
    } else {
        Write-Host "Desktop shortcut not found" -ForegroundColor Yellow
    }

    $startMenuShortcut = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Tax Calculator.lnk"
    if (Test-Path $startMenuShortcut) {
        Remove-Item $startMenuShortcut -Force
        Write-Host "Start menu shortcut removed" -ForegroundColor Green
    } else {
        Write-Host "Start menu shortcut not found" -ForegroundColor Yellow
    }

    # Remove registry entry
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($isAdmin) {
        try {
            $registryPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator"
            if (Test-Path $registryPath) {
                Remove-Item -Path $registryPath -Force
                Write-Host "Registry entry removed" -ForegroundColor Green
            }
        } catch {
            Write-Host "Could not remove registry entry: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    # Remove application files
    Write-Host "Removing application files..." -ForegroundColor Cyan
    Remove-Item -Path $installPath -Recurse -Force
    Write-Host "Application files removed" -ForegroundColor Green

    Write-Host ""
    Write-Host "===========================================" -ForegroundColor Green
    Write-Host "UNINSTALLATION COMPLETED SUCCESSFULLY!" -ForegroundColor Green
    Write-Host "===========================================" -ForegroundColor Green

} catch {
    Write-Host "Error during uninstallation: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Try running uninstaller as administrator" -ForegroundColor Yellow
}

Read-Host "Press Enter to exit"