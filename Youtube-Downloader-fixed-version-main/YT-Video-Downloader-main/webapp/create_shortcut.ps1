# PowerShell script to create desktop shortcut for YouTube Video Downloader

Write-Host "Creating Desktop Shortcut for YouTube Video Downloader..." -ForegroundColor Cyan
Write-Host ""

# Define paths
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "YouTube Video Downloader.lnk"
$targetPath = "c:\Users\sijjux\Desktop\YT-Video-Downloader-main\YT-Video-Downloader-main\webapp\launch.bat"

# Check if launch.bat exists
if (-not (Test-Path $targetPath)) {
    Write-Host "Error: launch.bat not found" -ForegroundColor Red
    exit 1
}

# Create WScript Shell object
$WScriptShell = New-Object -ComObject WScript.Shell

# Create the shortcut
$shortcut = $WScriptShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = "c:\Users\sijjux\Desktop\YT-Video-Downloader-main\YT-Video-Downloader-main\webapp"
$shortcut.Description = "Launch YouTube Video Downloader in Chrome"
$shortcut.WindowStyle = 1
$shortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,165"

# Save the shortcut
$shortcut.Save()

Write-Host ""
Write-Host "Desktop shortcut created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Shortcut location: $shortcutPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "How to use:" -ForegroundColor Yellow
Write-Host "  1. Double-click the YouTube Video Downloader icon on your desktop" -ForegroundColor White
Write-Host "  2. The server will start automatically" -ForegroundColor White
Write-Host "  3. Chrome will open to http://127.0.0.1:5000" -ForegroundColor White
Write-Host "  4. Start downloading videos!" -ForegroundColor White
Write-Host ""
Write-Host "All set! Enjoy your video downloader!" -ForegroundColor Green
