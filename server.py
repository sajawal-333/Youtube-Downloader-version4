import os
import threading
import time
import json
import re
import base64
import subprocess
from pathlib import Path
from typing import Optional
import tempfile
import shutil
import logging
from datetime import datetime
import uuid

from flask import Flask, request, jsonify, send_from_directory, send_file, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import yt_dlp
    logger.info(f"yt-dlp imported successfully (version: {yt_dlp.version.__version__})")
except Exception as e:
    logger.error(f"Failed to import yt-dlp: {e}")
    yt_dlp = None

# Check if ffmpeg is available
FFMPEG_AVAILABLE = False
try:
    result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
    FFMPEG_AVAILABLE = result.returncode == 0
    logger.info(f"ffmpeg available: {FFMPEG_AVAILABLE}")
except Exception:
    logger.info("ffmpeg not found on system")

app = Flask(__name__, static_folder="static", static_url_path="/")
CORS(app, expose_headers=['Content-Disposition'])

# Global progress storage
progress_storage = {}

# Persistent download directory (used as local temporary processing folder)
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"Local download directory: {DOWNLOAD_DIR}")

# Initialize Rate Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Supported URL Regex parsing
SUPPORTED_DOMAINS = [
    r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/.*',
    r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/.*',
    r'(?:https?:\/\/)?(?:www\.)?instagram\.com\/.*'
]

def is_valid_url(url: str) -> bool:
    """Check if the URL belongs to a supported platform."""
    if not url:
        return False
    for pattern in SUPPORTED_DOMAINS:
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False

# --- Cookie Management ---
COOKIE_FILE_PATH = None

def setup_cookies():
    """Set up cookies for YouTube authentication."""
    global COOKIE_FILE_PATH

    # Option 1: Base64 cookies from environment variable
    env_cookies = os.environ.get('YOUTUBE_COOKIES', '').strip()
    if env_cookies:
        try:
            decoded = base64.b64decode(env_cookies).decode('utf-8')
            cookie_path = Path(tempfile.gettempdir()) / 'yt_cookies.txt'
            cookie_path.write_text(decoded, encoding='utf-8')
            COOKIE_FILE_PATH = str(cookie_path)
            logger.info(f"Loaded cookies from YOUTUBE_COOKIES env var")
            return
        except Exception as e:
            logger.warning(f"Failed to decode YOUTUBE_COOKIES env var: {e}")

    # Option 2: cookies.txt file in project root
    local_cookie = Path(__file__).parent / 'cookies.txt'
    if local_cookie.is_file() and local_cookie.stat().st_size > 0:
        COOKIE_FILE_PATH = str(local_cookie)
        logger.info(f"Using local cookies file: {COOKIE_FILE_PATH}")
        return

    logger.info("No YouTube cookies configured.")

setup_cookies()


def build_format_string(max_height: str) -> str:
    """Build format string for the requested resolution.

    YouTube pre-muxed streams (best[ext=mp4]) are capped at 720p.
    For 1080p and above we MUST merge separate video+audio streams via ffmpeg.
    When ffmpeg is available we always prefer the highest-quality merged format
    so that 1080p / 1440p / 4K actually download at full resolution.
    """
    if FFMPEG_AVAILABLE:
        if max_height == 'best':
            # Absolute best: merge best video + best audio → output mp4
            return (
                'bestvideo[ext=mp4]+bestaudio[ext=m4a]'
                '/bestvideo+bestaudio'
                '/best[ext=mp4]/best'
            )
        try:
            h = int(max_height.replace('p', ''))
        except Exception:
            return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'

        # Merge at the requested height cap
        return (
            f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]'
            f'/bestvideo[height<={h}]+bestaudio'
            f'/best[height<={h}][ext=mp4]/best[ext=mp4]/best'
        )

    # --- ffmpeg NOT available: fall back to pre-muxed only (≤720p) ---
    if max_height == 'best':
        return 'best[ext=mp4]/best'
    try:
        h = int(max_height.replace('p', ''))
    except Exception:
        return 'best[ext=mp4]/best'
    return f'best[height<={h}][ext=mp4]/best[ext=mp4]/best'


def build_opts(output_dir: Path, quality: str, output_type: str, mp3_bitrate: int,
               referer: Optional[str] = None, user_agent: Optional[str] = None,
               extra_headers: Optional[dict] = None, progress_id: Optional[str] = None,
               format_id: Optional[str] = None) -> dict:
    """Build yt-dlp options dictionary"""
    if format_id:
        # If user explicitly selected a format ID from the info step
        if output_type == 'mp3':
            fmt = f"{format_id}[ext=m4a]/bestaudio/best"
        else:
            fmt = f"{format_id}+bestaudio[ext=m4a]/{format_id}/best[ext=mp4]/best"
    else:
        fmt = build_format_string(quality)
        
    output_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        'User-Agent': user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'Sec-Ch-Ua': '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
    }

    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)

    # Progress hook
    def progress_hook(d):
        if progress_id and d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    percentage = int((downloaded / total) * 100)
                    speed = d.get('speed', 0)
                    eta = d.get('eta', 0)
                    progress_storage[progress_id] = {
                        'percentage': percentage,
                        'downloaded': downloaded,
                        'total': total,
                        'speed': speed or 0,
                        'eta': eta or 0,
                        'status': 'downloading'
                    }
            except Exception as e:
                logger.error(f"Progress hook error: {e}")

    opts = {
        'format': fmt,
        'outtmpl': str(output_dir / '%(title)s [%(id)s].%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'extractor_retries': 3,
        'fragment_retries': 5,
        'retries': 5,
        'socket_timeout': 30,
        'sleep_interval': 1,
        'max_sleep_interval': 5,
        'ignoreerrors': False,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'http_headers': headers,
        'progress_hooks': [progress_hook] if progress_id else [],
        # 'web' client exposes all resolutions including 4K/1440p/1080p
        'extractor_args': {
            'youtube': {
                'player_client': ['web'],
            }
        },
    }

    # Add cookies if available
    if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
        opts['cookiefile'] = COOKIE_FILE_PATH
        logger.info("Using cookie file for authentication")

    # Post-processing for different output types
    if output_type == 'mp3':
        opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
        if FFMPEG_AVAILABLE:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': str(int(mp3_bitrate)),
            }]
    elif output_type == 'mp4' and FFMPEG_AVAILABLE:
        # Tell yt-dlp to mux merged video+audio streams into a single .mp4
        opts['merge_output_format'] = 'mp4'

    return opts


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe download"""
    filename = re.sub(r'[^\w\-_\.]', '_', filename)
    if len(filename) > 100:
        name, ext = os.path.splitext(filename)
        filename = name[:90] + ext
    if filename and not filename[0].isalnum():
        filename = 'video_' + filename
    return filename


# ---------- Download strategies ----------

def _try_download(url, temp_dir, opts, label="primary"):
    """Try downloading with the given options. Returns True on success."""
    try:
        logger.info(f"Attempting download ({label}), format: {opts.get('format')}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        downloaded_files = list(temp_dir.glob('*'))
        if downloaded_files and downloaded_files[0].stat().st_size > 0:
            f = downloaded_files[0]
            logger.info(f"Download succeeded ({label}): {f.name} ({f.stat().st_size} bytes)")
            return True
    except Exception as e:
        logger.warning(f"Download failed ({label}): {e}")
    return False


def download_with_fallbacks(url, temp_dir, quality, output_type, mp3_bitrate,
                            referer, user_agent, extra_headers, progress_id, format_id=None):
    """Try multiple download strategies."""

    # Strategy 1: Primary (pre-muxed preferred + web,android client)
    opts = build_opts(temp_dir, quality, output_type, mp3_bitrate,
                      referer, user_agent, extra_headers, progress_id, format_id)
    if _try_download(url, temp_dir, opts, "pre-muxed + web,android"):
        return True

    # Clean temp dir
    for f in temp_dir.glob('*'):
        f.unlink()

    # Strategy 2: iOS client with web fallback (bypasses bot detection)
    logger.info("Trying iOS + web client fallback...")
    opts2 = build_opts(temp_dir, quality, output_type, mp3_bitrate,
                       referer, user_agent, extra_headers, progress_id, format_id)
    opts2.pop('merge_output_format', None)
    opts2.pop('postprocessors', None)
    opts2['extractor_args'] = {
        'youtube': {
            'player_client': ['ios,web'],
        }
    }
    if _try_download(url, temp_dir, opts2, "ios+web client"):
        return True

    for f in temp_dir.glob('*'):
        f.unlink()

    # Strategy 3: TV client combined with Android
    logger.info("Trying tv + android fallback...")
    fallback_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'geo_bypass': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['tv,android'],
            }
        },
        'http_headers': {
            'User-Agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 14)',
        },
    }
    if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
        fallback_opts['cookiefile'] = COOKIE_FILE_PATH

    if _try_download(url, temp_dir, fallback_opts, "android UA"):
        return True

    return False


@app.route('/api/info', methods=['POST'])
@limiter.limit("20 per minute")
def get_video_info():
    """Fetch video metadata and available formats for the 2-step workflow."""
    if yt_dlp is None:
        return jsonify({'ok': False, 'error': 'yt-dlp is not available'}), 500

    data = request.get_json(force=True, silent=True) or request.form.to_dict()
    if not data:
        return jsonify({'ok': False, 'error': 'Invalid request data'}), 400

    url = (data.get('url') or '').strip()
    if not is_valid_url(url):
        return jsonify({'ok': False, 'error': 'Invalid or unsupported URL. Please use a YouTube or Instagram link.'}), 400

    opts = {
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'extractor_args': {'youtube': {'player_client': ['web,android']}},
    }
    
    if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
        opts['cookiefile'] = COOKIE_FILE_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = []
            if 'formats' in info:
                # Filter useful video formats for UI selection (e.g. mp4 with video)
                for f in info['formats']:
                    if f.get('vcodec') != 'none' and f.get('ext') == 'mp4' and f.get('height'):
                        formats.append({
                            'format_id': f['format_id'],
                            'resolution': f"{f['height']}p",
                            'ext': f.get('ext'),
                            'filesize': f.get('filesize') or f.get('filesize_approx') or 0
                        })
            
            # Sort formats by height descending
            formats = sorted(formats, key=lambda x: int(x['resolution'].replace('p', '')), reverse=True)
            
            # Handle Instagram (often only has 1 main format)
            platform = 'youtube' if 'youtube' in url.lower() or 'youtu.be' in url.lower() else 'instagram'

            return jsonify({
                'ok': True,
                'title': info.get('title', 'Video'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'platform': platform,
                'formats': formats
            })
            
    except Exception as e:
        logger.error(f"Error fetching info: {e}")
        error_msg = str(e)
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            error_msg = "Bot detection triggered. Please configure cookies."
        elif 'Private video' in error_msg:
            error_msg = "This video is private and cannot be downloaded."
            
        return jsonify({'ok': False, 'error': f'Failed to fetch video info: {error_msg}'}), 500


@app.route('/api/direct-download', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def direct_download():
    """Direct download endpoint that streams the file to user's browser"""
    temp_dir = None
    permanent_file = None
    progress_id = str(uuid.uuid4())

    try:
        if yt_dlp is None:
            return jsonify({'ok': False, 'error': 'yt-dlp not available on server'}), 500

        if request.method == 'GET':
            data = request.args.to_dict()
        else:
            try:
                data = request.get_json(force=True)
            except Exception:
                data = request.form.to_dict()
            
        if not data:
            return jsonify({'ok': False, 'error': 'Invalid parsing data format'}), 400

        url = (data.get('url') or '').strip()
        quality = (data.get('quality') or 'best').strip()
        output_type = (data.get('outputType') or 'mp4').strip()
        format_id = (data.get('format_id') or None)
        mp3_bitrate = int(data.get('mp3Bitrate') or 192)
        referer = (data.get('referer') or '').strip() or None
        user_agent = (data.get('userAgent') or '').strip() or None
        
        # Handle stringified JSON from form submits
        extra_headers = data.get('headers') or {}
        if isinstance(extra_headers, str):
            try:
                extra_headers = json.loads(extra_headers)
            except Exception:
                extra_headers = {}
                
        progress_id = data.get('progressId') or progress_id

        if not is_valid_url(url):
            return jsonify({'ok': False, 'error': 'Invalid or unsupported URL'}), 400

        logger.info(f"Starting download to temp local folder: {url} quality={quality} type={output_type} format={format_id}")

        progress_storage[progress_id] = {'percentage': 0, 'status': 'initializing'}

        # Process download directly into DOWNLOAD_DIR
        success = download_with_fallbacks(
            url, DOWNLOAD_DIR, quality, output_type, mp3_bitrate,
            referer, user_agent, extra_headers, progress_id, format_id
        )

        if not success:
            cookie_hint = ""
            if not COOKIE_FILE_PATH:
                cookie_hint = (
                    " To fix this, set YOUTUBE_COOKIES env var "
                    "(base64-encoded cookies.txt from your browser)."
                )
            return jsonify({
                'ok': False,
                'error': f'Download failed — YouTube may be blocking this request.{cookie_hint}'
            }), 500

        # Find the most recently downloaded file in DOWNLOAD_DIR
        downloaded_files = sorted(list(DOWNLOAD_DIR.glob('*')), key=os.path.getmtime, reverse=True)
        if not downloaded_files:
            return jsonify({'ok': False, 'error': 'No file was downloaded'}), 500

        file_path = downloaded_files[0]
        file_size = file_path.stat().st_size
        logger.info(f"Located download: {file_path.name} ({file_size} bytes)")

        if file_size == 0:
            return jsonify({'ok': False, 'error': 'Downloaded file is empty'}), 500

        # Determine the correct MIME type based on the file extension
        ext = file_path.suffix.lower()
        if not ext and output_type == 'mp4':
            ext = '.mp4'
        elif not ext and output_type == 'mp3':
            ext = '.mp3'
            
        mime_types = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.mkv': 'video/x-matroska',
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.ogg': 'audio/ogg',
            '.wav': 'audio/wav',
        }
        mimetype = mime_types.get(ext, 'application/octet-stream')

        # Build a clean download filename
        original_filename = file_path.name
        filename = sanitize_filename(original_filename)
        
        # Ensure correct extension is always present in the returned filename
        if output_type == 'mp4' and not filename.lower().endswith('.mp4'):
            filename = os.path.splitext(filename)[0] + '.mp4'
        elif output_type == 'mp3' and not filename.lower().endswith('.mp3'):
            filename = os.path.splitext(filename)[0] + '.mp3'

        # Make sure the response streams the file and cleans up afterwards
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
        
        @response.call_on_close
        def cleanup():
            try:
                logger.info(f"Cleaning up temp file: {file_path}")
                os.unlink(file_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {file_path}: {e}")

        logger.info(f"Serving: {filename} from local temp storage ({mimetype})")
        return response

    except Exception as e:
        logger.error(f"Error: {str(e)}")

        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
        if permanent_file and os.path.exists(permanent_file.name):
            try:
                os.unlink(permanent_file.name)
            except:
                pass

        error_msg = str(e)
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            error_msg = "YouTube bot detection triggered. Try adding cookies."

        return jsonify({'ok': False, 'error': error_msg}), 500
    finally:
        if progress_id in progress_storage:
            del progress_storage[progress_id]


@app.route('/api/progress/<progress_id>', methods=['GET'])
def get_progress(progress_id):
    """Get download progress"""
    progress = progress_storage.get(progress_id, {'percentage': 0, 'status': 'unknown'})
    return jsonify(progress)

@app.route('/api/download', methods=['POST'])
def api_download():
    return jsonify({'ok': True, 'message': 'Use direct-download endpoint'})

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/test')
def test():
    return jsonify({
        'ok': True,
        'message': 'Server is working',
        'yt_dlp_available': yt_dlp is not None,
        'ffmpeg_available': FFMPEG_AVAILABLE,
        'cookies_configured': COOKIE_FILE_PATH is not None,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'healthy',
        'yt_dlp_available': yt_dlp is not None,
        'ffmpeg_available': FFMPEG_AVAILABLE,
        'cookies_configured': COOKIE_FILE_PATH is not None,
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting server on port {port}")
    logger.info(f"ffmpeg: {'yes' if FFMPEG_AVAILABLE else 'no'}, cookies: {'yes' if COOKIE_FILE_PATH else 'no'}")
    app.run(host='0.0.0.0', port=port, debug=False)
