@echo off
echo ============================================
echo   PSG CAS Careers Portal - Starting Server
echo ============================================
echo.
echo Server URL: http://localhost:5000
echo Admin:      http://localhost:5000/admin.html
echo.
echo Press Ctrl+C to stop the server.
echo.
cd /d "%~dp0"
python app.py
pause
