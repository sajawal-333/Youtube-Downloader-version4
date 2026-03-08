@echo off
title YouTube Video Downloader
color 0A

echo.
echo ========================================
echo   YouTube Video Downloader
echo   Starting server...
echo ========================================
echo.

REM Navigate to the webapp directory
cd /d "c:\Users\sijjux\Desktop\YT-Video-Downloader-main\YT-Video-Downloader-main\webapp"

REM Check if server is already running on port 5000
netstat -ano | findstr :5000 > nul
if %errorlevel% equ 0 (
    echo Server is already running!
    echo Opening Chrome browser...
    timeout /t 2 > nul
    start chrome "http://127.0.0.1:5000"
    echo.
    echo Chrome opened! You can close this window.
    timeout /t 3 > nul
    exit
)

REM Start the server in a new window
echo Starting Flask server...
start "YouTube Downloader Server" /min cmd /c "python server.py"

REM Wait for server to start
echo Waiting for server to initialize...
timeout /t 5 > nul

REM Open Chrome browser
echo Opening Chrome browser...
start chrome "http://127.0.0.1:5000"

echo.
echo ========================================
echo   Server is running!
echo   Chrome browser opened.
echo   
echo   URL: http://127.0.0.1:5000
echo   
echo   Keep this window open to keep
echo   the server running.
echo   
echo   Press Ctrl+C to stop the server.
echo ========================================
echo.

REM Keep the window open
pause
