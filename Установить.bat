@echo off
chcp 65001 > nul

title Установка Калькулятора Транспортного Налога
echo.
echo ========================================
echo   УСТАНОВКА
echo   Калькулятор Транспортного Налога
echo ========================================
echo.

:: Проверяем права администратора
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Запущено от имени администратора
) else (
    echo [INFO] Запущено без прав администратора
)
echo.

:: Проверяем наличие exe
if not exist "dist\tax_app.exe" (
    echo [ERROR] Файл dist\tax_app.exe не найден!
    echo Сначала запустите сборку: pyinstaller tax_app.spec
    pause
    exit /b 1
)

:: Выбор директории установки через диалог
echo Выберите папку для установки...
powershell -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $dlg = New-Object System.Windows.Forms.FolderBrowserDialog; $dlg.Description = 'Выберите папку для установки'; $dlg.RootFolder = 'MyComputer'; $dlg.SelectedPath = [Environment]::GetFolderPath('Desktop'); if ($dlg.ShowDialog() -eq 'OK') { Write-Output $dlg.SelectedPath }" > "%TEMP%\install_path.txt"

set /p INSTALL_DIR=<"%TEMP%\install_path.txt"
del "%TEMP%\install_path.txt" >nul 2>&1

if not defined INSTALL_DIR (
    echo [ERROR] Папка не выбрана
    pause
    exit /b 1
)

:: Добавляем имя папки
set "INSTALL_DIR=%INSTALL_DIR%\КалькуляторТН"

:: Создаем директорию
echo.
echo Установка в: %INSTALL_DIR%
echo.
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: Копируем файлы
echo Копирование файлов...
copy /Y "dist\tax_app.exe" "%INSTALL_DIR%\" >nul 2>&1

:: Проверяем иконку и копируем
if exist "icon.ico" (
    copy /Y "icon.ico" "%INSTALL_DIR%\" >nul 2>&1
    set "ICON_PATH=%INSTALL_DIR%\icon.ico"
) else (
    set "ICON_PATH=%INSTALL_DIR%\tax_app.exe"
)

if %errorlevel% equ 0 (
    echo [OK] Файлы скопированы
) else (
    echo [ERROR] Ошибка копирования файлов
    pause
    exit /b 1
)

:: Создаем ярлык на рабочем столе
echo.
echo Создание ярлыков...
powershell -ExecutionPolicy Bypass -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\Калькулятор ТН.lnk'); $s.TargetPath = '%INSTALL_DIR%\tax_app.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'Калькулятор транспортного налога'; $s.IconLocation = '%ICON_PATH%'; $s.Save()"

:: Создаем ярлык в меню Пуск
if not exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs" mkdir "%APPDATA%\Microsoft\Windows\Start Menu\Programs"
powershell -ExecutionPolicy Bypass -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%APPDATA%\Microsoft\Windows\Start Menu\Programs\Калькулятор ТН.lnk'); $s.TargetPath = '%INSTALL_DIR%\tax_app.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'Калькулятор транспортного налога'; $s.IconLocation = '%ICON_PATH%'; $s.Save()"

echo [OK] Ярлыки созданы

:: Регистрация в реестре
echo.
echo Регистрация в системе...
set "REG_KEY=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator"
reg add "%REG_KEY%" /v "DisplayName" /t REG_SZ /d "Калькулятор Транспортного Налога" /f >nul 2>&1
reg add "%REG_KEY%" /v "DisplayVersion" /t REG_SZ /d "1.0" /f >nul 2>&1
reg add "%REG_KEY%" /v "Publisher" /t REG_SZ /d "TaxCalculator" /f >nul 2>&1
reg add "%REG_KEY%" /v "InstallLocation" /t REG_SZ /d "%INSTALL_DIR%" /f >nul 2>&1
reg add "%REG_KEY%" /v "UninstallString" /t REG_SZ /d "cmd /c \"\"%INSTALL_DIR%\Удалить.bat\"\" " /f >nul 2>&1
reg add "%REG_KEY%" /v "DisplayIcon" /t REG_SZ /d "%ICON_PATH%" /f >nul 2>&1
reg add "%REG_KEY%" /v "NoModify" /t REG_DWORD /d 1 /f >nul 2>&1
reg add "%REG_KEY%" /v "NoRepair" /t REG_DWORD /d 1 /f >nul 2>&1
echo [OK] Регистрация завершена

:: Копируем скрипт удаления
copy /Y "Удалить.bat" "%INSTALL_DIR%\" >nul 2>&1

echo.
echo ========================================
echo   УСТАНОВКА ЗАВЕРШЕНА!
echo ========================================
echo.
echo Папка: %INSTALL_DIR%
echo.
echo Запустите: Дважды щелкните ярлык на рабочем столе
echo.
pause
