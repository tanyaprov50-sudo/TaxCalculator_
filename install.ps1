# Tax Calculator - Installer
# PowerShell Installer Script

param(
    [string]$InstallPath = "$env:LOCALAPPDATA\TaxCalculator",
    [switch]$Force
)

Write-Host "===========================================" -ForegroundColor Green
Write-Host "      Tax Calculator Installer           " -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Green
Write-Host ""

$updateMode = $false

# Check admin privileges
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# Installation path selection
Write-Host "Select installation location:" -ForegroundColor Cyan
Write-Host "1) Local user folder (recommended): $env:LOCALAPPDATA\TaxCalculator" -ForegroundColor White
Write-Host "2) Custom folder (you will be prompted to choose)" -ForegroundColor White
if ($isAdmin) {
    Write-Host "3) Program Files (requires admin rights): ${env:ProgramFiles}\TaxCalculator" -ForegroundColor White
}
Write-Host ""

$choice = Read-Host "Choose installation type (1-3, default 1)"
if (-not $choice) { $choice = "1" }

switch ($choice) {
    "1" {
        $InstallPath = "$env:LOCALAPPDATA\TaxCalculator"
        Write-Host "Installing to user folder: $InstallPath" -ForegroundColor Cyan
    }
    "2" {
        # Custom folder selection using Windows Forms
        Write-Host "Opening folder selection dialog..." -ForegroundColor Yellow

            # Custom folder selection loop
            $pathSelected = $false
            while (-not $pathSelected) {
                try {
                    Add-Type -AssemblyName System.Windows.Forms
                    $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
                    $folderBrowser.Description = "Select installation folder for Tax Calculator"
                    $folderBrowser.RootFolder = "MyComputer"
                    $folderBrowser.SelectedPath = $env:USERPROFILE

                    $result = $folderBrowser.ShowDialog()
                    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
                        $selectedPath = $folderBrowser.SelectedPath
                        $InstallPath = Join-Path $selectedPath "TaxCalculator"

                        # Check if TaxCalculator subfolder already exists
                        if (Test-Path $InstallPath) {
                            $overwrite = Read-Host "Folder '$InstallPath' already exists. Overwrite? (y/n)"
                            if ($overwrite -eq "y" -or $overwrite -eq "Y") {
                                $Force = $true
                                $pathSelected = $true
                            } else {
                                Write-Host "Please choose a different folder." -ForegroundColor Yellow
                                continue
                            }
                        } else {
                            $pathSelected = $true
                        }

                        Write-Host "Installing to: $InstallPath" -ForegroundColor Cyan
                    } else {
                        Write-Host "Installation cancelled" -ForegroundColor Yellow
                        exit 0
                    }
                } catch {
                    Write-Host "Folder browser not available. Please enter path manually:" -ForegroundColor Yellow
                    $manualPath = Read-Host "Enter installation path (full path to parent folder)"
                    if ($manualPath) {
                        $InstallPath = Join-Path $manualPath "TaxCalculator"

                        # Check if path exists
                        if (Test-Path $InstallPath) {
                            $overwrite = Read-Host "Folder '$InstallPath' already exists. Overwrite? (y/n)"
                            if ($overwrite -eq "y" -or $overwrite -eq "Y") {
                                $Force = $true
                                $pathSelected = $true
                            } else {
                                Write-Host "Please choose a different folder." -ForegroundColor Yellow
                                continue
                            }
                        } else {
                            $pathSelected = $true
                        }

                        Write-Host "Installing to: $InstallPath" -ForegroundColor Cyan
                    } else {
                        Write-Host "Installation cancelled" -ForegroundColor Yellow
                        exit 0
                    }
                }
            }
    }
    "3" {
        if ($isAdmin) {
            $InstallPath = "${env:ProgramFiles}\TaxCalculator"
            Write-Host "Installing to Program Files: $InstallPath" -ForegroundColor Cyan
        } else {
            Write-Host "Admin rights required for Program Files installation. Using user folder instead." -ForegroundColor Yellow
            $InstallPath = "$env:LOCALAPPDATA\TaxCalculator"
        }
    }
    default {
        $InstallPath = "$env:LOCALAPPDATA\TaxCalculator"
        Write-Host "Invalid choice. Installing to user folder: $InstallPath" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Installation folder: $InstallPath" -ForegroundColor Cyan

try {
    # Stop running processes
    Write-Host "Stopping running processes..." -ForegroundColor Yellow
    $processes = Get-Process -Name "tax_app" -ErrorAction SilentlyContinue
    if ($processes) {
        $processes | Stop-Process -Force
        Start-Sleep -Seconds 2
        Write-Host "Running processes stopped" -ForegroundColor Green
    }

    # Handle existing installation
    if (Test-Path $InstallPath) {
        if (-not $Force) {
            Write-Host "Installation folder exists." -ForegroundColor Yellow
            $choice = Read-Host "Choose action: 1) Overwrite 2) Update existing 3) Choose different location (default 2)"
            if (-not $choice) { $choice = "2" }

            switch ($choice) {
                "1" {
                    Write-Host "Will overwrite existing installation..." -ForegroundColor Cyan
                    $Force = $true
                }
                "2" {
                    Write-Host "Updating existing installation..." -ForegroundColor Cyan
                    $updateMode = $true
                }
                "3" {
                    Write-Host "Please choose a different location." -ForegroundColor Yellow
                    # For custom selection, we already handled this in the selection loop
                    # For predefined locations, we'll create a timestamped backup
                    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
                    $InstallPath = "${InstallPath}_$timestamp"
                    Write-Host "Using new installation path: $InstallPath" -ForegroundColor Cyan
                }
                default {
                    Write-Host "Updating existing installation..." -ForegroundColor Cyan
                    $updateMode = $true
                }
            }
        }

        if ($Force) {
            Write-Host "Removing old installation..." -ForegroundColor Yellow
            try {
                # More aggressive process termination
                Get-Process | Where-Object { $_.Path -like "*TaxCalculator*" -or $_.Modules.FileName -like "*TaxCalculator*" } | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
                Remove-Item -Path $InstallPath -Recurse -Force -ErrorAction Stop
                Write-Host "Old installation removed" -ForegroundColor Green
            } catch {
                Write-Host "Removal failed. Creating new installation folder..." -ForegroundColor Yellow
                $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
                $InstallPath = "${InstallPath}_$timestamp"
                Write-Host "Using new installation path: $InstallPath" -ForegroundColor Cyan
            }
        }
    }

    if (-not $updateMode) {
        New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
        Write-Host "Installation folder created" -ForegroundColor Green
    }

    # Copy files
    Write-Host "Copying application files..." -ForegroundColor Cyan
    $sourceDir = "$PSScriptRoot\dist\tax_app.dist"

    if (-not (Test-Path $sourceDir)) {
        throw "Application folder not found: $sourceDir"
    }

    # Copy application files
    if ($updateMode) {
        Write-Host "Updating application files..." -ForegroundColor Cyan
        try {
            # In update mode, copy with error handling for locked files
            Get-ChildItem -Path $sourceDir -Recurse | ForEach-Object {
                $destPath = $_.FullName.Replace($sourceDir, $InstallPath)
                $destDir = Split-Path $destPath -Parent
                if (-not (Test-Path $destDir)) {
                    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
                }
                try {
                    Copy-Item -Path $_.FullName -Destination $destPath -Force -ErrorAction Stop
                } catch {
                    Write-Host "Warning: Could not update $($_.Name)" -ForegroundColor Yellow
                }
            }
            Write-Host "Application files updated" -ForegroundColor Green
        } catch {
            Write-Host "Warning: Update completed with errors: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    } else {
        try {
            Copy-Item -Path "$sourceDir\*" -Destination $InstallPath -Recurse -Force -ErrorAction Stop
            Write-Host "Application files copied" -ForegroundColor Green
        } catch {
            Write-Host "Warning: Some files could not be copied: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    # Copy icon file
    if (Test-Path "$PSScriptRoot\icon.ico") {
        try {
            Copy-Item -Path "$PSScriptRoot\icon.ico" -Destination $InstallPath -Force
            Write-Host "Icon file copied" -ForegroundColor Green
        } catch {
            Write-Host "Warning: Could not copy icon file" -ForegroundColor Yellow
        }
    }

    # Verify exe file exists
    if (-not (Test-Path "$InstallPath\tax_app.exe")) {
        throw "Application executable not found. Installation may be corrupted."
    }

    # Create shortcuts regardless of copy success
    $iconPath = if (Test-Path "$InstallPath\icon.ico") { "$InstallPath\icon.ico" } else { "$InstallPath\tax_app.exe" }

    # Create desktop shortcut
    try {
        $desktopPath = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = "$desktopPath\Tax Calculator.lnk"

        $WshShell = New-Object -comObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($shortcutPath)
        $Shortcut.TargetPath = "$InstallPath\tax_app.exe"
        $Shortcut.WorkingDirectory = $InstallPath
        $Shortcut.Description = "Tax Calculator"
        $Shortcut.IconLocation = $iconPath
        $Shortcut.Save()
        Write-Host "Desktop shortcut created" -ForegroundColor Green
    } catch {
        Write-Host "Could not create desktop shortcut: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    # Create Start Menu shortcut
    try {
        $startMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
        if (-not (Test-Path $startMenuPath)) {
            New-Item -ItemType Directory -Path $startMenuPath -Force | Out-Null
        }
        $startMenuShortcut = "$startMenuPath\Tax Calculator.lnk"

        $Shortcut2 = $WshShell.CreateShortcut($startMenuShortcut)
        $Shortcut2.TargetPath = "$InstallPath\tax_app.exe"
        $Shortcut2.WorkingDirectory = $InstallPath
        $Shortcut2.Description = "Tax Calculator"
        $Shortcut2.IconLocation = $iconPath
        $Shortcut2.Save()
        Write-Host "Start Menu shortcut created" -ForegroundColor Green
    } catch {
        Write-Host "Could not create Start Menu shortcut: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    # Add registry entry for uninstall
    if ($isAdmin) {
        try {
            $registryPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator"
            New-Item -Path $registryPath -Force | Out-Null
            Set-ItemProperty -Path $registryPath -Name "DisplayName" -Value "Tax Calculator"
            Set-ItemProperty -Path $registryPath -Name "DisplayVersion" -Value "1.0"
            Set-ItemProperty -Path $registryPath -Name "InstallLocation" -Value $InstallPath
            Set-ItemProperty -Path $registryPath -Name "UninstallString" -Value "powershell.exe -File `"$InstallPath\uninstall.ps1`""
            Set-ItemProperty -Path $registryPath -Name "Publisher" -Value "TaxCalculator"
            Write-Host "Registry entry created" -ForegroundColor Green
        } catch {
            Write-Host "Could not create registry entry: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    # Create uninstall info file
    $uninstallInfo = @"
[Uninstall]
InstallPath=$InstallPath
InstallDate=$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Version=1.0
"@
    $uninstallFile = Join-Path $InstallPath "uninstall.ini"
    try {
        $uninstallInfo | Out-File -FilePath $uninstallFile -Encoding UTF8 -Force
        Write-Host "Uninstall info saved" -ForegroundColor Gray
    } catch {
        Write-Host "Warning: Could not save uninstall info" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "===========================================" -ForegroundColor Green
    Write-Host "    INSTALLATION COMPLETED SUCCESSFULLY!  " -ForegroundColor Green
    Write-Host "===========================================" -ForegroundColor Green
    Write-Host "Application installed to: $InstallPath" -ForegroundColor Cyan
    Write-Host "Shortcuts created on desktop and Start Menu" -ForegroundColor Cyan
    Write-Host ""

    $runNow = Read-Host "Run application now? (y/N)"
    if ($runNow -eq "y" -or $runNow -eq "Y") {
        Start-Process "$InstallPath\tax_app.exe"
    }
    
} catch {
    Write-Host "Installation error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Try running installer as administrator" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Read-Host "Press Enter to exit"