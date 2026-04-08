@echo off
chcp 65001 >nul
echo ========================================
echo Reset and launch TaxCalculator
echo ========================================
echo.

cd /d "%~dp0"

echo Deleting old databases...
del /q "fleet_*.db" 2>nul
del /q "vehicle_fleet.db" 2>nul
del /q "organizations.json" 2>nul
del /q "tax_config_cache.json" 2>nul
del /q "custom_rates.json" 2>nul
echo Done.
echo.

echo Starting program...
start "" "dist\tax_app.exe"
echo.
echo Program started. Now:
echo   1. Create new organization
echo   2. Click "Import Excel"
echo   3. Select test_fleet.xlsx
echo   4. Check PAZ has status "spisan" and Q4 = "-"
echo.
pause
