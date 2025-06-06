import os
import json
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_file, Response
from pytube import YouTube
from bs4 import BeautifulSoup
import requests
import re
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB max file size
app.config['UPLOAD_FOLDER'] = 'downloads'

# Ensure download directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Proxies configuration (to be used with yt-dlp)
PROXIES = [
    'http://45.77.99.210:3128',
    'http://45.77.98.245:3128',
    'http://45.77.101.41:3128',
    'http://45.32.102.29:3128',
    'http://45.63.27.78:3128',
    'http://45.63.25.9:3128',
    'http://45.63.26.176:3128',
    'http://45.63.27.78:3128',
    'http://45.63.0.178:3128',
    'http://45.63.4.200:3128'
]

def get_available_qualities(yt):
    """Get available video qualities"""
    streams = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc()
    return [stream.resolution for stream in streams if stream.resolution]

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[\\/*?:"<>|]', '', filename)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        yt = YouTube(url)
        video_info = {
            'title': yt.title,
            'author': yt.author,
            'length': str(yt.length // 60) + ':' + str(yt.length % 60).zfill(2),
            'views': f"{yt.views:,}",
            'publish_date': yt.publish_date.strftime('%Y-%m-%d') if yt.publish_date else 'N/A',
            'thumbnail': yt.thumbnail_url,
            'qualities': get_available_qualities(yt)
        }
        return jsonify(video_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    quality = data.get('quality', 'best')
    download_type = data.get('type', 'video')  # 'video' or 'audio'
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if download_type == 'video' else 'bestaudio/best',
            'outtmpl': os.path.join(app.config['UPLOAD_FOLDER'], '%(title)s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'proxy': PROXIES[0] if PROXIES else None
        }

        if download_type == 'video' and quality != 'best':
            ydl_opts['format'] = f'bestvideo[height<={quality[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality[:-1]}]/best'
        elif download_type == 'audio':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            filename = ydl.prepare_filename(info)
            ydl.process_info(info)

            # Get the actual downloaded file path
            if download_type == 'audio':
                filename = os.path.splitext(filename)[0] + '.mp3'

            return jsonify({
                'success': True,
                'filename': os.path.basename(filename)
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/download_file/<filename>')
def download_file(filename):
    try:
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], filename),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return str(e), 404

@app.route('/get_thumbnail')
def get_thumbnail():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        yt = YouTube(url)
        return jsonify({'thumbnail': yt.thumbnail_url})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/get_video_info')
def get_video_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        yt = YouTube(url)
        info = {
            'title': yt.title,
            'author': yt.author,
            'length': str(yt.length // 60) + ':' + str(yt.length % 60).zfill(2),
            'views': f"{yt.views:,}",
            'publish_date': yt.publish_date.strftime('%Y-%m-%d') if yt.publish_date else 'N/A',
            'description': yt.description,
            'keywords': ', '.join(yt.keywords) if hasattr(yt, 'keywords') else 'N/A',
            'rating': round(yt.rating, 2) if hasattr(yt, 'rating') and yt.rating else 'N/A',
            'age_restricted': yt.age_restricted,
            'channel_url': yt.channel_url,
            'embed_url': yt.embed_url,
        }
        
        # Save to text file
        filename = sanitize_filename(f"{yt.title}_info.txt")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for key, value in info.items():
                f.write(f"{key.replace('_', ' ').title()}: {value}\n")
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
