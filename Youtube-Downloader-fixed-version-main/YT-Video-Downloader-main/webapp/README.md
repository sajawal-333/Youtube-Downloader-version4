# 🎬 YouTube Video Downloader

A professional, fast, and user-friendly web application to download YouTube videos in various formats and qualities.

![Status](https://img.shields.io/badge/status-active-success.svg)
![Python](https://img.shields.io/badge/python-3.11-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## ✨ Features

- 🎥 **Multiple Quality Options** - 360p to 4K (2160p)
- 🎵 **MP3 Audio Extraction** - Download audio only
- ⚡ **Fast Downloads** - Optimized performance
- 🎨 **Professional UI** - Modern, clean design
- 📱 **Mobile Responsive** - Works on all devices
- 🔒 **Secure** - HTTPS support
- 🆓 **Free to Use** - No registration required

## 🚀 Quick Start

### Local Development

1. **Clone the repository**
```bash
git clone https://github.com/YOUR_USERNAME/video-downloader.git
cd video-downloader/webapp
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Run the server**
```bash
python server.py
```

4. **Open in browser**
```
http://127.0.0.1:5000
```

## 📦 Deployment

### Option 1: Railway.app (Recommended - FREE)

1. Push code to GitHub
2. Go to [railway.app](https://railway.app)
3. Click "Deploy from GitHub repo"
4. Select your repository
5. Wait 2-3 minutes
6. Your app is live! 🎉

**Detailed deployment guide:** See `deployment_guide.md`

### Option 2: One-Click Deployment

Run the automated deployment preparation script:

```powershell
.\deploy_prepare.ps1
```

Then follow the on-screen instructions.

## 🛠️ Tech Stack

- **Backend:** Flask (Python)
- **Downloader:** yt-dlp
- **Frontend:** HTML5, CSS3, JavaScript
- **Server:** Gunicorn
- **Font:** Inter (Google Fonts)

## 📋 Requirements

- Python 3.11+
- Flask 2.3.3
- yt-dlp (latest)
- gunicorn 21.2.0

## 🎯 Usage

1. Paste a YouTube URL
2. Select quality (360p - 4K)
3. Choose format (MP4 or MP3)
4. Click "Download Now"
5. File downloads to your browser!

### Advanced Options

- Custom Referer header
- Custom User Agent
- Extra HTTP headers

## 📸 Screenshots

### Main Interface
Clean, professional design with intuitive controls.

### Download Progress
Real-time progress bar with status updates.

## 🔧 Configuration

### Environment Variables

- `PORT` - Server port (default: 5000)

### Customization

Edit `static/index.html` to customize the UI.

## 🐛 Troubleshooting

### Downloads fail
- Update yt-dlp: `pip install --upgrade yt-dlp`
- Check internet connection
- Verify video URL is valid

### Server won't start
- Check if port 5000 is available
- Verify all dependencies are installed
- Check Python version (3.11+ required)

## 📝 License

This project is licensed under the MIT License.

## ⚖️ Legal Notice

This tool is for educational purposes only. Users are responsible for complying with YouTube's Terms of Service and applicable copyright laws. Only download content you have the right to download.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues and questions, please open an issue on GitHub.

## 🌟 Acknowledgments

- Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- UI inspired by modern web design principles
- Font: [Inter](https://fonts.google.com/specimen/Inter)

---

**Made with ❤️ for easy video downloads**
