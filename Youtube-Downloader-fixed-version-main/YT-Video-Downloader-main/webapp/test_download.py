import requests
import json

# Test the YouTube video downloader
# Using a short, public domain test video

print("Testing YouTube Video Downloader...")
print("-" * 50)

# Test 1: Check if server is running
print("\n1. Testing server health...")
try:
    response = requests.get("http://127.0.0.1:5000/api/test")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Server is running")
        print(f"  - yt-dlp available: {data.get('yt_dlp_available')}")
        print(f"  - Timestamp: {data.get('timestamp')}")
    else:
        print(f"✗ Server returned status code: {response.status_code}")
        exit(1)
except Exception as e:
    print(f"✗ Failed to connect to server: {e}")
    exit(1)

# Test 2: Try to download a short YouTube video
# Using a very short test video (YouTube's test video)
print("\n2. Testing video download...")
print("   Using a short test video from YouTube...")

test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo" - first YouTube video (18 seconds)

payload = {
    "url": test_url,
    "quality": "360p",  # Use lower quality for faster testing
    "outputType": "mp4",
    "mp3Bitrate": 192
}

try:
    print(f"   Downloading: {test_url}")
    print(f"   Quality: {payload['quality']}")
    print(f"   Format: {payload['outputType']}")
    print("\n   This may take a moment...")
    
    response = requests.post(
        "http://127.0.0.1:5000/api/direct-download",
        json=payload,
        timeout=120  # 2 minute timeout
    )
    
    if response.status_code == 200:
        # Get filename from Content-Disposition header
        content_disposition = response.headers.get('Content-Disposition', '')
        filename = 'test_video.mp4'
        if 'filename=' in content_disposition:
            filename = content_disposition.split('filename=')[1].strip('"')
        
        # Save the file
        output_path = f"c:\\Users\\sijjux\\Desktop\\{filename}"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        file_size = len(response.content) / (1024 * 1024)  # Convert to MB
        print(f"\n✓ Download successful!")
        print(f"  - File saved to: {output_path}")
        print(f"  - File size: {file_size:.2f} MB")
        print(f"  - Filename: {filename}")
    else:
        error_data = response.json() if response.headers.get('content-type') == 'application/json' else {}
        print(f"\n✗ Download failed!")
        print(f"  - Status code: {response.status_code}")
        print(f"  - Error: {error_data.get('error', 'Unknown error')}")
        exit(1)
        
except requests.exceptions.Timeout:
    print("\n✗ Download timed out (took longer than 2 minutes)")
    exit(1)
except Exception as e:
    print(f"\n✗ Download failed with error: {e}")
    exit(1)

print("\n" + "=" * 50)
print("All tests passed! ✓")
print("The YouTube Video Downloader is working correctly.")
print("=" * 50)
