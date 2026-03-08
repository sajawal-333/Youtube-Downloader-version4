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

# ── ffmpeg detection ────────────────────────────────────────────────────────
FFMPEG_AVAILABLE = False
FFMPEG_PATH = None

def _find_ffmpeg():
    global FFMPEG_AVAILABLE, FFMPEG_PATH
    for candidate in ['ffmpeg', '/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg']:
        try:
            result = subprocess.run(
                [candidate, '-version'],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                FFMPEG_AVAILABLE = True
                FFMPEG_PATH = candidate
                logger.info(f"ffmpeg found at: {candidate}")
                return
        except Exception:
            continue
    logger.warning("ffmpeg NOT found — high-quality merging (1080p+) will be unavailable")

_find_ffmpeg()

app = Flask(__name__, static_folder="static", static_url_path="/")
CORS(app, expose_headers=['Content-Disposition'])

# Global progress storage
progress_storage = {}

# Persistent download directory
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"Local download directory: {DOWNLOAD_DIR}")

# Rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Supported URL patterns
SUPPORTED_DOMAINS = [
    r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/.*',
    r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/.*',
    r'(?:https?:\/\/)?(?:www\.)?instagram\.com\/.*'
]

def is_valid_url(url: str) -> bool:
    if not url:
        return False
    for pattern in SUPPORTED_DOMAINS:
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False

# ── Cookie management ────────────────────────────────────────────────────────
COOKIE_FILE_PATH = None

def setup_cookies():
    global COOKIE_FILE_PATH
    env_cookies = os.environ.get('YOUTUBE_COOKIES', '').strip()
    if env_cookies:
        try:
            decoded = base64.b64decode(env_cookies).decode('utf-8')
            cookie_path = Path(tempfile.gettempdir()) / 'yt_cookies.txt'
            cookie_path.write_text(decoded, encoding='utf-8')
            COOKIE_FILE_PATH = str(cookie_path)
            logger.info("Loaded cookies from YOUTUBE_COOKIES env var")
            return
        except Exception as e:
            logger.warning(f"Failed to decode YOUTUBE_COOKIES env var: {e}")

    local_cookie = Path(__file__).parent / 'cookies.txt'
    if local_cookie.is_file() and local_cookie.stat().st_size > 0:
        COOKIE_FILE_PATH = str(local_cookie)
        logger.info(f"Using local cookies file: {COOKIE_FILE_PATH}")
        return

    logger.info("No YouTube cookies configured.")

setup_cookies()

# ── Quality / format helpers ─────────────────────────────────────────────────

# All quality tiers we support (displayed in UI)
QUALITY_TIERS = [
    {'label': '4K Ultra HD',  'height': 2160, 'tag': '4k'},
    {'label': '1440p QHD',    'height': 1440, 'tag': '1440p'},
    {'label': '1080p Full HD','height': 1080, 'tag': '1080p'},
    {'label': '720p HD',      'height': 720,  'tag': '720p'},
    {'label': '480p',         'height': 480,  'tag': '480p'},
    {'label': '360p',         'height': 360,  'tag': '360p'},
]

def build_format_string(max_height: str) -> str:
    """
    Build the best possible yt-dlp format selector for the requested height.

    Strategy (when ffmpeg is available):
      - Always prefer  bestvideo + bestaudio  merged into mp4.
      - This guarantees true 4K/1440p/1080p — YouTube never provides these
        as pre-muxed streams.
      - Fallback chain ensures something always downloads even on restricted videos.

    Strategy (no ffmpeg):
      - Can only use pre-muxed streams which YouTube caps at 720p.
      - We still try to get the best available within that cap.
    """
    if max_height == 'best':
        if FFMPEG_AVAILABLE:
            return (
                # VP9 4K / AV1 preferred over H.264 for quality, fall back to mp4
                'bestvideo[ext=webm]+bestaudio[ext=webm]'
                '/bestvideo[ext=mp4]+bestaudio[ext=m4a]'
                '/bestvideo+bestaudio'
                '/best'
            )
        return 'best[ext=mp4]/best'

    try:
        h = int(str(max_height).replace('p', ''))
    except Exception:
        return build_format_string('best')

    if FFMPEG_AVAILABLE:
        return (
            # Prefer VP9/AV1 for resolutions ≥ 720p (better quality)
            f'bestvideo[height<={h}][ext=webm]+bestaudio[ext=webm]'
            f'/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]'
            f'/bestvideo[height<={h}]+bestaudio'
            f'/best[height<={h}][ext=mp4]'
            f'/best[height<={h}]'
            f'/best[ext=mp4]/best'
        )

    # No ffmpeg — pre-muxed only (≤720p hard limit by YouTube)
    safe_h = min(h, 720)
    return (
        f'best[height<={safe_h}][ext=mp4]'
        f'/best[height<={safe_h}]'
        f'/best[ext=mp4]/best'
    )


def build_opts(output_dir: Path, quality: str, output_type: str, mp3_bitrate: int,
               referer: Optional[str] = None, user_agent: Optional[str] = None,
               extra_headers: Optional[dict] = None, progress_id: Optional[str] = None,
               format_id: Optional[str] = None) -> dict:
    """Build yt-dlp options dictionary."""

    if format_id:
        if output_type == 'mp3':
            fmt = f"{format_id}/bestaudio/best"
        else:
            # Merge selected video stream with best audio
            fmt = (
                f"{format_id}+bestaudio[ext=m4a]"
                f"/{format_id}+bestaudio"
                f"/{format_id}"
                f"/best[ext=mp4]/best"
            )
    else:
        fmt = build_format_string(quality)

    output_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        'User-Agent': user_agent or (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/131.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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

    def progress_hook(d):
        if not progress_id:
            return
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                pct = int((downloaded / total) * 100) if total > 0 else 0
                progress_storage[progress_id] = {
                    'percentage': pct,
                    'downloaded': downloaded,
                    'total': total,
                    'speed': d.get('speed') or 0,
                    'eta': d.get('eta') or 0,
                    'status': 'downloading'
                }
            except Exception as e:
                logger.error(f"Progress hook error: {e}")
        elif d['status'] == 'finished':
            if progress_id in progress_storage:
                progress_storage[progress_id]['status'] = 'merging'

    opts = {
        'format': fmt,
        'outtmpl': str(output_dir / '%(title)s [%(id)s].%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'extractor_retries': 5,
        'fragment_retries': 10,
        'retries': 10,
        'socket_timeout': 60,
        'sleep_interval': 1,
        'max_sleep_interval': 5,
        'ignoreerrors': False,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'http_headers': headers,
        'progress_hooks': [progress_hook] if progress_id else [],
        'extractor_args': {
            'youtube': {
                # web_creator gives access to higher bitrate audio + better format availability
                'player_client': ['web', 'android', 'web_creator'],
            }
        },
        # Write thumbnail alongside video (optional, remove if unwanted)
        # 'writethumbnail': True,
    }

    if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
        opts['cookiefile'] = COOKIE_FILE_PATH
        logger.info("Using cookie file for authentication")

    # ── Post-processors ──────────────────────────────────────────────────────
    if output_type == 'mp3':
        opts['format'] = 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best'
        if FFMPEG_AVAILABLE:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': str(int(mp3_bitrate)),
            }]
            opts['ffmpeg_location'] = FFMPEG_PATH

    elif output_type in ('mp4', 'mkv', 'webm') and FFMPEG_AVAILABLE:
        # Always re-mux / merge into a clean container
        opts['merge_output_format'] = output_type if output_type != 'mp4' else 'mp4'
        opts['ffmpeg_location'] = FFMPEG_PATH
        # Embed metadata & chapters when available
        opts['postprocessors'] = [
            {'key': 'FFmpegMetadata', 'add_chapters': True},
        ]

    return opts


def sanitize_filename(filename: str) -> str:
    filename = re.sub(r'[^\w\-_\. ]', '_', filename)
    filename = filename.strip()
    if len(filename) > 120:
        name, ext = os.path.splitext(filename)
        filename = name[:110].strip() + ext
    if filename and not filename[0].isalnum():
        filename = 'video_' + filename
    return filename


# ── Download with multi-strategy fallback ───────────────────────────────────

def _try_download(url, temp_dir, opts, label="primary"):
    """Attempt a download. Returns (success: bool, file_path: Path|None)."""
    try:
        logger.info(f"[{label}] format={opts.get('format')}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)

        files = [f for f in temp_dir.glob('*') if f.is_file() and f.stat().st_size > 0]
        if files:
            # Pick largest file (in case thumbnails etc. were written)
            f = max(files, key=lambda x: x.stat().st_size)
            logger.info(f"[{label}] ✓ {f.name} ({f.stat().st_size:,} bytes)")
            return True
    except Exception as e:
        logger.warning(f"[{label}] ✗ {e}")
    return False


def download_with_fallbacks(url, output_dir, quality, output_type, mp3_bitrate,
                            referer, user_agent, extra_headers, progress_id,
                            format_id=None):
    """
    Try multiple download strategies in descending quality preference.
    Returns True if any strategy succeeded.
    """
    def clean_dir():
        for f in output_dir.glob('*'):
            try:
                f.unlink()
            except Exception:
                pass

    # ── Strategy 1: web + android + web_creator (best quality + coverage) ──
    opts1 = build_opts(output_dir, quality, output_type, mp3_bitrate,
                       referer, user_agent, extra_headers, progress_id, format_id)
    if _try_download(url, output_dir, opts1, "web+android+web_creator"):
        return True
    clean_dir()

    # ── Strategy 2: android client only (avoids some bot detection) ──
    logger.info("Fallback → android client only")
    opts2 = build_opts(output_dir, quality, output_type, mp3_bitrate,
                       referer, user_agent, extra_headers, progress_id, format_id)
    opts2['extractor_args'] = {'youtube': {'player_client': ['android']}}
    if _try_download(url, output_dir, opts2, "android"):
        return True
    clean_dir()

    # ── Strategy 3: tv_embedded client (bypasses some restrictions) ──
    logger.info("Fallback → tv_embedded client")
    opts3 = build_opts(output_dir, quality, output_type, mp3_bitrate,
                       referer, user_agent, extra_headers, progress_id, format_id)
    opts3['extractor_args'] = {'youtube': {'player_client': ['tv_embedded']}}
    if _try_download(url, output_dir, opts3, "tv_embedded"):
        return True
    clean_dir()

    # ── Strategy 4: android UA with simplified format string ──
    logger.info("Fallback → android UA + simplified format")
    if output_type == 'mp3':
        fallback_fmt = 'bestaudio/best'
    elif FFMPEG_AVAILABLE:
        h = quality.replace('p', '') if quality not in ('best', '') else '2160'
        fallback_fmt = (
            f'bestvideo[height<={h}]+bestaudio'
            f'/bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]'
            f'/best[ext=mp4]/best'
        )
    else:
        fallback_fmt = 'best[ext=mp4]/best'

    opts4 = {
        'format': fallback_fmt,
        'merge_output_format': 'mp4',
        'outtmpl': str(output_dir / '%(title)s [%(id)s].%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'geo_bypass': True,
        'extractor_retries': 5,
        'fragment_retries': 10,
        'retries': 10,
        'socket_timeout': 60,
        'extractor_args': {'youtube': {'player_client': ['android']}},
        'http_headers': {
            'User-Agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 14) gzip',
        },
    }
    if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
        opts4['cookiefile'] = COOKIE_FILE_PATH
    if FFMPEG_AVAILABLE:
        opts4['ffmpeg_location'] = FFMPEG_PATH

    if _try_download(url, output_dir, opts4, "android-ua-simplified"):
        return True
    clean_dir()

    # ── Strategy 5: absolute last resort — any available format ──
    logger.info("Last resort → any available format")
    opts5 = {
        'format': 'best',
        'outtmpl': str(output_dir / '%(title)s [%(id)s].%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_check_certificate': True,
        'geo_bypass': True,
        'retries': 5,
    }
    if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
        opts5['cookiefile'] = COOKIE_FILE_PATH
    return _try_download(url, output_dir, opts5, "last-resort")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/api/info', methods=['POST'])
@limiter.limit("20 per minute")
def get_video_info():
    """
    Fetch video metadata + ALL available formats (360p → 4K).
    Returns structured format list suitable for quality-picker UI.
    """
    if yt_dlp is None:
        return jsonify({'ok': False, 'error': 'yt-dlp is not available'}), 500

    data = request.get_json(force=True, silent=True) or request.form.to_dict()
    if not data:
        return jsonify({'ok': False, 'error': 'Invalid request data'}), 400

    url = (data.get('url') or '').strip()
    if not is_valid_url(url):
        return jsonify({'ok': False,
                        'error': 'Invalid or unsupported URL. Use a YouTube or Instagram link.'}), 400

    info_opts = {
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'no_check_certificate': True,
        'extractor_args': {
            'youtube': {'player_client': ['web', 'android', 'web_creator']}
        },
    }
    if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
        info_opts['cookiefile'] = COOKIE_FILE_PATH

    try:
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # ── Build rich format list ───────────────────────────────────────────
        raw_formats = info.get('formats', [])

        # Video formats: collect unique heights with best quality per height
        height_map = {}
        for f in raw_formats:
            h = f.get('height')
            vcodec = f.get('vcodec', 'none')
            if not h or vcodec == 'none':
                continue

            fs = f.get('filesize') or f.get('filesize_approx') or 0
            tbr = f.get('tbr') or 0
            existing = height_map.get(h)

            # Prefer higher bitrate / filesize
            if existing is None or tbr > existing.get('tbr', 0):
                height_map[h] = {
                    'format_id': f['format_id'],
                    'height': h,
                    'ext': f.get('ext', 'mp4'),
                    'vcodec': vcodec,
                    'acodec': f.get('acodec', 'none'),
                    'tbr': tbr,
                    'filesize': fs,
                    'fps': f.get('fps') or 0,
                    'dynamic_range': f.get('dynamic_range') or 'SDR',
                }

        # Map to quality tiers
        video_formats = []
        for tier in QUALITY_TIERS:
            h = tier['height']
            # Find closest available height ≤ tier height
            available_heights = [ah for ah in height_map if ah <= h]
            if not available_heights:
                continue
            best_h = max(available_heights)
            f = height_map[best_h]

            label = tier['label'] if best_h == h else f"{best_h}p"
            needs_merge = f['acodec'] == 'none'  # separate video stream, needs ffmpeg merge

            video_formats.append({
                'format_id': f['format_id'],
                'label': label,
                'resolution': f"{best_h}p",
                'height': best_h,
                'ext': 'mp4',  # we always output mp4
                'vcodec': f['vcodec'],
                'fps': int(f['fps']) if f['fps'] else None,
                'filesize': f['filesize'],
                'tbr': f['tbr'],
                'dynamic_range': f['dynamic_range'],
                'needs_merge': needs_merge,
                'ffmpeg_required': needs_merge,
                'tag': tier['tag'],
            })

        # Audio-only formats
        audio_formats = []
        seen_abr = set()
        for f in sorted(raw_formats,
                        key=lambda x: x.get('abr') or x.get('tbr') or 0,
                        reverse=True):
            if f.get('vcodec', 'none') != 'none':
                continue
            abr = int(f.get('abr') or f.get('tbr') or 0)
            if abr == 0 or abr in seen_abr:
                continue
            seen_abr.add(abr)
            audio_formats.append({
                'format_id': f['format_id'],
                'label': f"{abr}kbps {f.get('ext','').upper()}",
                'abr': abr,
                'ext': f.get('ext', 'm4a'),
                'acodec': f.get('acodec', ''),
                'filesize': f.get('filesize') or f.get('filesize_approx') or 0,
            })
            if len(audio_formats) >= 5:
                break

        platform = ('youtube'
                    if 'youtube' in url.lower() or 'youtu.be' in url.lower()
                    else 'instagram')

        return jsonify({
            'ok': True,
            'title': info.get('title', 'Video'),
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration'),
            'view_count': info.get('view_count'),
            'uploader': info.get('uploader') or info.get('channel'),
            'upload_date': info.get('upload_date'),
            'platform': platform,
            'ffmpeg_available': FFMPEG_AVAILABLE,
            'formats': video_formats,
            'audio_formats': audio_formats,
        })

    except Exception as e:
        logger.error(f"Error fetching info: {e}")
        error_msg = str(e)
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            error_msg = "Bot detection triggered. Please configure cookies."
        elif 'Private video' in error_msg:
            error_msg = "This video is private and cannot be downloaded."
        elif 'This video is not available' in error_msg:
            error_msg = "This video is not available in your region."
        return jsonify({'ok': False, 'error': f'Failed to fetch video info: {error_msg}'}), 500


@app.route('/api/direct-download', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def direct_download():
    """Stream the downloaded file directly to the user's browser."""
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
            return jsonify({'ok': False, 'error': 'Invalid request data'}), 400

        url         = (data.get('url') or '').strip()
        quality     = (data.get('quality') or 'best').strip()
        output_type = (data.get('outputType') or 'mp4').strip()
        format_id   = data.get('format_id') or None
        mp3_bitrate = int(data.get('mp3Bitrate') or 192)
        referer     = (data.get('referer') or '').strip() or None
        user_agent  = (data.get('userAgent') or '').strip() or None
        progress_id = data.get('progressId') or progress_id

        extra_headers = data.get('headers') or {}
        if isinstance(extra_headers, str):
            try:
                extra_headers = json.loads(extra_headers)
            except Exception:
                extra_headers = {}

        if not is_valid_url(url):
            return jsonify({'ok': False, 'error': 'Invalid or unsupported URL'}), 400

        logger.info(
            f"Download request: url={url} quality={quality} "
            f"type={output_type} format_id={format_id} ffmpeg={FFMPEG_AVAILABLE}"
        )

        progress_storage[progress_id] = {'percentage': 0, 'status': 'initializing'}

        success = download_with_fallbacks(
            url, DOWNLOAD_DIR, quality, output_type, mp3_bitrate,
            referer, user_agent, extra_headers, progress_id, format_id
        )

        if not success:
            hint = ""
            if not COOKIE_FILE_PATH:
                hint = (" Tip: set the YOUTUBE_COOKIES env var "
                        "(base64-encoded Netscape cookies.txt) to bypass bot detection.")
            if not FFMPEG_AVAILABLE:
                hint += " Note: ffmpeg is not installed — downloads are limited to ≤720p."
            return jsonify({
                'ok': False,
                'error': f'Download failed — YouTube may be blocking this request.{hint}'
            }), 500

        # Find the most recently created file
        files = sorted(
            [f for f in DOWNLOAD_DIR.glob('*') if f.is_file() and f.stat().st_size > 0],
            key=os.path.getmtime, reverse=True
        )
        if not files:
            return jsonify({'ok': False, 'error': 'No file was downloaded'}), 500

        file_path = files[0]
        file_size = file_path.stat().st_size
        logger.info(f"Serving: {file_path.name} ({file_size:,} bytes)")

        ext = file_path.suffix.lower()
        mime_map = {
            '.mp4':  'video/mp4',
            '.webm': 'video/webm',
            '.mkv':  'video/x-matroska',
            '.mp3':  'audio/mpeg',
            '.m4a':  'audio/mp4',
            '.ogg':  'audio/ogg',
            '.wav':  'audio/wav',
            '.opus': 'audio/opus',
        }
        mimetype = mime_map.get(ext, 'application/octet-stream')

        filename = sanitize_filename(file_path.name)

        # Enforce correct extension
        ext_map = {'mp4': '.mp4', 'mp3': '.mp3', 'webm': '.webm', 'mkv': '.mkv', 'm4a': '.m4a'}
        desired_ext = ext_map.get(output_type)
        if desired_ext and not filename.lower().endswith(desired_ext):
            filename = os.path.splitext(filename)[0] + desired_ext

        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )

        @response.call_on_close
        def _cleanup():
            try:
                os.unlink(file_path)
                logger.info(f"Cleaned up: {file_path.name}")
            except Exception as ce:
                logger.warning(f"Cleanup failed for {file_path}: {ce}")

        return response

    except Exception as e:
        logger.error(f"Direct download error: {e}")
        error_msg = str(e)
        if 'Sign in to confirm' in error_msg or 'bot' in error_msg.lower():
            error_msg = "YouTube bot detection triggered. Configure cookies to fix."
        return jsonify({'ok': False, 'error': error_msg}), 500

    finally:
        progress_storage.pop(progress_id, None)


@app.route('/api/progress/<progress_id>', methods=['GET'])
def get_progress(progress_id):
    progress = progress_storage.get(progress_id, {'percentage': 0, 'status': 'unknown'})
    return jsonify(progress)


@app.route('/api/formats', methods=['GET'])
def list_quality_tiers():
    """Return the supported quality tiers and server capabilities."""
    return jsonify({
        'ok': True,
        'ffmpeg_available': FFMPEG_AVAILABLE,
        'max_quality': '4K (2160p)' if FFMPEG_AVAILABLE else '720p (no ffmpeg)',
        'quality_tiers': QUALITY_TIERS,
        'note': (
            'Resolutions above 720p require ffmpeg for merging separate video+audio streams.'
            if not FFMPEG_AVAILABLE else
            'All resolutions supported (360p – 4K).'
        )
    })


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/test')
def test():
    return jsonify({
        'ok': True,
        'message': 'Server is working',
        'yt_dlp_available': yt_dlp is not None,
        'yt_dlp_version': yt_dlp.version.__version__ if yt_dlp else None,
        'ffmpeg_available': FFMPEG_AVAILABLE,
        'ffmpeg_path': FFMPEG_PATH,
        'cookies_configured': COOKIE_FILE_PATH is not None,
        'max_quality': '4K' if FFMPEG_AVAILABLE else '720p',
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
    logger.info(f"ffmpeg: {'YES (' + str(FFMPEG_PATH) + ')' if FFMPEG_AVAILABLE else 'NO — max 720p'}")
    logger.info(f"cookies: {'yes' if COOKIE_FILE_PATH else 'no'}")
    app.run(host='0.0.0.0', port=port, debug=False)