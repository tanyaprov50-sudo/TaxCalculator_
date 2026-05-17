@echo off
chcp 65001 > nul

title Удаление Калькулятора Транспортного Налога

echo.
echo ========================================
echo   УДАЛЕНИЕ
echo   Калькулятор Транспортного Налога
echo ========================================
echo.

:: Проверяем права администратора
net session >nul 2>&1
if %errorlevel% == 0 (
    echo [OK] Удаление запущено от имени администратора
) else (
    echo [WARN] Рекомендуются права администратора!
    echo.
)

:: Запрос подтверждения
echo.
echo [WARN] ВНИМАНИЕ! Будет удалена вся программа!
echo.
set /p "confirm=Вы уверены? (y/N): "
if /i not "%confirm%"=="y" (
    echo Операция отменена.
    pause
    exit /b
)

:: Получаем путь установки из реестра
echo.
echo Поиск установленной программы...
set "INSTALL_DIR="

:: Сначала пробуем получить из реестра
for /f "tokens=2*" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator" /v "InstallLocation" 2^>nul') do (
    set "INSTALL_DIR=%%~b"
)

if defined INSTALL_DIR (
    echo [OK] Найден в реестре: %INSTALL_DIR%
    goto :verify_path
)

echo [INFO] Не найден в реестре, поиск на дисках...

:: Ищем на всех дисках
for %%d in (C D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    if exist "%%d:\КалькуляторТН\tax_app.exe" (
        set "INSTALL_DIR=%%d:\КалькуляторТН"
        goto :found_path
    )
)

:: Если не найден - спрашиваем пользователя
echo.
echo [ERROR] Программа не найдена автоматически.
echo.
set /p "INSTALL_DIR=Введите путь к папке с программой: "
if not defined INSTALL_DIR (
    echo [ERROR] Путь не указан
    pause
    exit /b 1
)
goto :verify_path

:found_path
echo [OK] Найден на диске: %INSTALL_DIR%

:verify_path

:: Проверяем что это правильная папка
if not exist "%INSTALL_DIR%\tax_app.exe" (
    echo [ERROR] В указанной папке нет tax_app.exe
    pause
    exit /b 1
)

echo Найдено: %INSTALL_DIR%

:: Останавливаем процесс если запущен
echo.
echo Остановка приложения...
taskkill /F /IM tax_app.exe >nul 2>&1

:: Удаляем директорию
echo.
echo Удаление файлов...
if exist "%INSTALL_DIR%" (
    rmdir /S /Q "%INSTALL_DIR%" 2>nul
    if exist "%INSTALL_DIR%" (
        takeown /f "%INSTALL_DIR%" /r /d y >nul 2>&1
        icacls "%INSTALL_DIR%" /grant administrators:F /t >nul 2>&1
        rmdir /S /Q "%INSTALL_DIR%" >nul 2>&1
    )
)

if not exist "%INSTALL_DIR%" (
    echo [OK] Файлы удалены
) else (
    echo [WARN] Не удалось удалить некоторые файлы
)

:: Удаляем ярлыки
echo.
echo Удаление ярлыков...
del /F /Q "%USERPROFILE%\Desktop\Калькулятор ТН.lnk" >nul 2>&1
del /F /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Калькулятор ТН.lnk" >nul 2>&1
echo [OK] Ярлыки удалены

:: Удаляем из реестра
echo.
echo Очистка реестра...
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator" /f >nul 2>&1
if %errorLevel% equ 0 (
    echo [OK] Реестр очищен
) else (
    echo [WARN] Не удалось очистить реестр (возможно, нужны права администратора)
)

:: Пробуем также удалить из HKCU на всякий случай
reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\TaxCalculator" /f >nul 2>&1

echo.
echo ========================================
echo   УДАЛЕНИЕ ЗАВЕРШЕНО!
echo ========================================
pause