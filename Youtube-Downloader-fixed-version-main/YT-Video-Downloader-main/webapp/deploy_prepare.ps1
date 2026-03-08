# Quick Deployment Script for GitHub
# Run this to prepare your project for deployment

Write-Host "🚀 YouTube Video Downloader - Deployment Preparation" -ForegroundColor Cyan
Write-Host "=" * 60

# Check if git is installed
Write-Host "`n📋 Checking prerequisites..." -ForegroundColor Yellow
try {
    git --version | Out-Null
    Write-Host "✅ Git is installed" -ForegroundColor Green
} catch {
    Write-Host "❌ Git is not installed. Please install Git first:" -ForegroundColor Red
    Write-Host "   Download from: https://git-scm.com/download/win"
    exit 1
}

# Navigate to webapp directory
$webappPath = "c:\Users\sijjux\Desktop\YT-Video-Downloader-main\YT-Video-Downloader-main\webapp"
Set-Location $webappPath
Write-Host "✅ Changed to webapp directory" -ForegroundColor Green

# Create .gitignore if it doesn't exist
Write-Host "`n📝 Creating .gitignore..." -ForegroundColor Yellow
$gitignoreContent = @"
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
*.log
.DS_Store
test_download.py
*.mp4
*.mp3
"@
Set-Content -Path ".gitignore" -Value $gitignoreContent
Write-Host "✅ Created .gitignore" -ForegroundColor Green

# Verify required files exist
Write-Host "`n🔍 Verifying required files..." -ForegroundColor Yellow
$requiredFiles = @("server.py", "requirements.txt", "Procfile", "runtime.txt")
$allFilesExist = $true

foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "✅ $file exists" -ForegroundColor Green
    } else {
        Write-Host "❌ $file is missing!" -ForegroundColor Red
        $allFilesExist = $false
    }
}

if (-not $allFilesExist) {
    Write-Host "`n❌ Some required files are missing. Please ensure all files are present." -ForegroundColor Red
    exit 1
}

# Initialize git repository
Write-Host "`n🔧 Initializing Git repository..." -ForegroundColor Yellow
if (Test-Path ".git") {
    Write-Host "⚠️  Git repository already exists" -ForegroundColor Yellow
} else {
    git init
    Write-Host "✅ Git repository initialized" -ForegroundColor Green
}

# Add all files
Write-Host "`n📦 Adding files to Git..." -ForegroundColor Yellow
git add .
Write-Host "✅ Files added" -ForegroundColor Green

# Commit
Write-Host "`n💾 Creating initial commit..." -ForegroundColor Yellow
git commit -m "Initial commit - YouTube Video Downloader with professional UI"
Write-Host "✅ Initial commit created" -ForegroundColor Green

# Instructions for GitHub
Write-Host "`n" + ("=" * 60) -ForegroundColor Cyan
Write-Host "🎉 Repository prepared successfully!" -ForegroundColor Green
Write-Host ("=" * 60) -ForegroundColor Cyan

Write-Host "`n📋 Next Steps:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Create a new repository on GitHub:" -ForegroundColor White
Write-Host "   → Go to: https://github.com/new" -ForegroundColor Cyan
Write-Host "   → Name: video-downloader" -ForegroundColor Cyan
Write-Host "   → Make it Public or Private" -ForegroundColor Cyan
Write-Host "   → DO NOT initialize with README" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Connect and push to GitHub:" -ForegroundColor White
Write-Host "   Run these commands:" -ForegroundColor Cyan
Write-Host ""
Write-Host "   git remote add origin https://github.com/YOUR_USERNAME/video-downloader.git" -ForegroundColor Yellow
Write-Host "   git branch -M main" -ForegroundColor Yellow
Write-Host "   git push -u origin main" -ForegroundColor Yellow
Write-Host ""
Write-Host "3. Deploy on Railway.app (FREE):" -ForegroundColor White
Write-Host "   → Go to: https://railway.app" -ForegroundColor Cyan
Write-Host "   → Click 'Start a New Project'" -ForegroundColor Cyan
Write-Host "   → Choose 'Deploy from GitHub repo'" -ForegroundColor Cyan
Write-Host "   → Select your repository" -ForegroundColor Cyan
Write-Host "   → Wait 2-3 minutes for deployment" -ForegroundColor Cyan
Write-Host "   → Your app will be live!" -ForegroundColor Cyan
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "✨ Ready to deploy! Follow the steps above." -ForegroundColor Green
Write-Host ("=" * 60) -ForegroundColor Cyan
