# Freeytzone - YouTube Video Downloader

Freeytzone is a web application that allows users to download YouTube videos and audios in various qualities. It provides a user-friendly interface to search for videos, view their details, and download them in different formats.

## Features

- Download YouTube videos in multiple qualities (up to 2K)
- Download audio in MP3 format
- Download video thumbnails
- Download video information in text format
- Modern and responsive UI
- Supports both desktop and mobile devices

## Prerequisites

- Python 3.7 or higher
- pip (Python package installer)
- FFmpeg (required for audio conversion)

## Installation

1. Clone the repository or download the source code

2. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

3. Install FFmpeg:
   - **Windows**: Download from [FFmpeg's official website](https://ffmpeg.org/download.html) and add it to your system PATH
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt-get install ffmpeg`

## Configuration

1. Open `app.py` and add your proxies (if needed) to the `PROXIES` list:
   ```python
   PROXIES = [
       'http://username:password@ip:port',
       'http://ip:port',
   ]
   ```

## Running the Application

1. Start the Flask development server:
   ```
   python app.py
   ```

2. Open your web browser and navigate to:
   ```
   http://localhost:5000
   ```

## Usage

1. Paste a YouTube URL in the input field
2. Click the "Search" button
3. View the video details
4. Choose your preferred download option:
   - **Video**: Download in various qualities
   - **Audio**: Download as MP3
   - **Video Info**: Download video details as a text file
   - **Thumbnail**: Download the video thumbnail

## Project Structure

```
Freeytzone/
├── app.py                # Main Flask application
├── requirements.txt      # Python dependencies
├── README.md            # This file
├── templates/
│   └── index.html      # Main HTML template
└── downloads/           # Directory for downloaded files (created automatically)
```

## Troubleshooting

- If you encounter a "403 Forbidden" error, try adding working proxies to the `PROXIES` list in `app.py`
- Make sure FFmpeg is installed and accessible in your system PATH
- Ensure you have the latest version of yt-dlp: `pip install --upgrade yt-dlp`

## Legal Notice

This application is for educational purposes only. Please respect YouTube's Terms of Service and only download videos that you have the right to download.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
