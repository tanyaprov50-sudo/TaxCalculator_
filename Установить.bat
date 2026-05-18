@echo off
chcp 65001 > nul

:: Всегда работаем из папки этого bat-файла
cd /d "%~dp0"

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
    echo [ERROR] Запущено без прав администратора!
    echo Для установки необходимы права администратора.
    echo Правой кнопкой мыши на этот файл - "Запуск от имени администратора"
    pause
    exit /b 1
)
echo.

:: Проверяем наличие exe
if not exist "dist\tax_app.exe" (
    echo [ERROR] Файл dist\tax_app.exe не найден!
    echo.
    echo Сначала необходимо собрать приложение.
    echo Запуск сборки...
    echo.
    :: Переходим в папку проекта перед сборкой
    cd /d "%~dp0"
    :: Запускаем PyInstaller с правильным путём
    pyinstaller --clean tax_app.spec
    if %errorLevel% neq 0 (
        echo [ERROR] Ошибка сборки приложения!
        pause
        exit /b 1
    )
    echo.
    if not exist "dist\tax_app.exe" (
        echo [ERROR] После сборки файл dist\tax_app.exe так и не был найден!
        pause
        exit /b 1
    )
    echo [OK] Приложение собрано успешно!
    echo.
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
if %errorLevel% neq 0 (
    echo [ERROR] Ошибка копирования tax_app.exe
    pause
    exit /b 1
)

:: Проверяем иконку и копируем
set "ICON_PATH=%INSTALL_DIR%\tax_app.exe"
if exist "icon.ico" (
    copy /Y "icon.ico" "%INSTALL_DIR%\" >nul 2>&1
    if %errorLevel% equ 0 (
        set "ICON_PATH=%INSTALL_DIR%\icon.ico"
        echo [OK] Иконка скопирована
    )
)

echo [OK] Файлы скопированы

:: Создаем ярлык на рабочем столе
echo.
echo Создание ярлыков...
powershell -ExecutionPolicy Bypass -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\Калькулятор ТН.lnk'); $s.TargetPath = '%INSTALL_DIR%\tax_app.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'Калькулятор транспортного налога'; $s.IconLocation = '%ICON_PATH%'; $s.Save()"
if %errorLevel% equ 0 (
    echo [OK] Ярлык на рабочем столе создан
) else (
    echo [WARN] Не удалось создать ярлык на рабочем столе
)

:: Создаем ярлык в меню Пуск
if not exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs" mkdir "%APPDATA%\Microsoft\Windows\Start Menu\Programs" 2>nul
powershell -ExecutionPolicy Bypass -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%APPDATA%\Microsoft\Windows\Start Menu\Programs\Калькулятор ТН.lnk'); $s.TargetPath = '%INSTALL_DIR%\tax_app.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.Description = 'Калькулятор транспортного налога'; $s.IconLocation = '%ICON_PATH%'; $s.Save()"
if %errorLevel% equ 0 (
    echo [OK] Ярлык в меню Пуск создан
) else (
    echo [WARN] Не удалось создать ярлык в меню Пуск
)

:: Регистрация в реестре
echo.
echo Регистрация в системе...
set "REG_KEY=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator"

:: Копируем скрипт удаления до регистрации деинсталлятора
copy /Y "Удалить.bat" "%INSTALL_DIR%\" >nul 2>&1
if %errorLevel% equ 0 (
    echo [OK] Скрипт удаления скопирован
) else (
    echo [WARN] Не удалось скопировать скрипт удаления
)

reg add "%REG_KEY%" /v "DisplayName" /t REG_SZ /d "Калькулятор Транспортного Налога" /f >nul 2>&1
if %errorLevel% neq 0 (
    echo [WARN] Не удалось записать DisplayName в реестр
)
reg add "%REG_KEY%" /v "DisplayVersion" /t REG_SZ /d "2.0" /f >nul 2>&1
reg add "%REG_KEY%" /v "Publisher" /t REG_SZ /d "TaxCalculator" /f >nul 2>&1
reg add "%REG_KEY%" /v "InstallLocation" /t REG_SZ /d "%INSTALL_DIR%" /f >nul 2>&1
reg add "%REG_KEY%" /v "UninstallString" /t REG_SZ /d "\"%INSTALL_DIR%\Удалить.bat\"" /f >nul 2>&1
reg add "%REG_KEY%" /v "DisplayIcon" /t REG_SZ /d "%ICON_PATH%" /f >nul 2>&1
reg add "%REG_KEY%" /v "NoModify" /t REG_DWORD /d 1 /f >nul 2>&1
reg add "%REG_KEY%" /v "NoRepair" /t REG_DWORD /d 1 /f >nul 2>&1
echo [OK] Регистрация в реестре завершена

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
