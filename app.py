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

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s %(module)s.%(funcName)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)

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
        logger.error(f"Error getting video info for {url}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Could not retrieve video information: {str(e)}'}), 500

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
                    # Proxy will be handled in the loop
            'noplaylist': True,
            'quiet': False, # Set to False to capture more error details
            'no_warnings': False, # Set to False to capture more error details
            'extract_flat': 'discard_in_playlist', # Avoids downloading playlist items if a single video URL from a playlist is given
            'skip_download': True, # We only want to extract info first to get title for filename
            'ignoreerrors': True, # Continue on download errors for individual formats
            'verbose': True # More verbose output for debugging
        }

        # Initial info extraction to get the title for the filename template
        # This first call will use the default proxy or no proxy if not set in ydl_opts_info
        # We do this to get the title before attempting download with multiple proxies
        ydl_opts_info = ydl_opts.copy()
        # Ensure we don't try to download with this call, just get info
        ydl_opts_info['skip_download'] = True 
        # Remove proxy from initial info call, or set a default if preferred
        # ydl_opts_info.pop('proxy', None) 

        logger.debug(f"Initial ydl_opts for info extraction: {ydl_opts_info}")
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl_info_extractor:
            try:
                info = ydl_info_extractor.extract_info(url, download=False)
                base_title = info.get('title', 'untitled_video')
                sanitized_title = sanitize_filename(base_title)
                logger.info(f"Successfully extracted video title: {sanitized_title}")
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"Initial info extraction failed for {url}: {str(e)}", exc_info=True)
                # Try to extract a more specific error message
                error_message = str(e)
                if hasattr(e, 'exc_info') and e.exc_info and e.exc_info[1]:
                    error_message = str(e.exc_info[1])
                return jsonify({'error': f'Failed to fetch video metadata: {error_message}'}), 500
            except Exception as e:
                logger.error(f"Unexpected error during initial info extraction for {url}: {str(e)}", exc_info=True)
                return jsonify({'error': f'An unexpected error occurred while fetching video metadata: {str(e)}'}), 500

        # Update outtmpl with the sanitized title
        # The extension will be determined by yt-dlp
        ydl_opts['outtmpl'] = os.path.join(app.config['UPLOAD_FOLDER'], f'{sanitized_title}.%(ext)s')
        ydl_opts['skip_download'] = False # Now we want to download

        # Attempt download with proxy rotation
        download_successful = False
        downloaded_filename = None
        last_error = "Failed to download after trying all available proxies."

        # Create a list of proxies to try, including an option for no proxy
        proxies_to_try = PROXIES + [None] if PROXIES else [None]

        for proxy_url in proxies_to_try:
            current_ydl_opts = ydl_opts.copy()
            if proxy_url:
                current_ydl_opts['proxy'] = proxy_url
                logger.info(f"Attempting download for {url} using proxy: {proxy_url}")
            else:
                current_ydl_opts.pop('proxy', None) # Remove proxy key if None
                logger.info(f"Attempting download for {url} without proxy")
            
            logger.debug(f"Current ydl_opts for download attempt: {current_ydl_opts}")

            try:
                with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                    # Extract info again, this time it will also download because skip_download is False
                    # and outtmpl is set.
                    # Using process_info might be better if info is already mostly correct from above,
                    # but extract_info is safer if format selection depends on proxy.
                    download_info = ydl.extract_info(url, download=True)
                    
                    # Determine the filename yt-dlp would use/has used.
                    # yt-dlp might change the extension, e.g., for audio conversion.
                    # The 'filename' key in info_dict is usually the final path after download and postprocessing.
                    # If 'requested_downloads' is present, it's more reliable.
                    if download_info.get('requested_downloads') and len(download_info['requested_downloads']) > 0:
                        # This is the most reliable path after all processing
                        final_filepath = download_info['requested_downloads'][0]['filepath']
                    else:
                        # Fallback: try to construct from info if 'requested_downloads' is not available
                        # This might not be 100% accurate if postprocessing changes extension and ydl.prepare_filename was based on original info
                        temp_filename_info = ydl.prepare_filename(download_info) # Get filename based on possibly updated info
                        if download_type == 'audio':
                            # yt-dlp usually saves audio as .mp3 after postprocessing
                            final_filepath = os.path.splitext(temp_filename_info)[0] + '.mp3'
                            # Verify if the file actually exists with .mp3, otherwise use the original extension from prepare_filename
                            if not os.path.exists(final_filepath):
                                final_filepath = temp_filename_info # fallback to whatever prepare_filename gave
                                logger.warning(f"MP3 file {os.path.splitext(temp_filename_info)[0] + '.mp3'} not found, using {final_filepath}")
                        else:
                            final_filepath = temp_filename_info

                    logger.info(f"Download successful with proxy {proxy_url if proxy_url else 'None'}. File path: {final_filepath}")
                    downloaded_filename = os.path.basename(final_filepath)
                    download_successful = True
                    break # Exit loop on successful download

            except yt_dlp.utils.DownloadError as e:
                logger.warning(f"Download failed with proxy {proxy_url if proxy_url else 'None'} for {url}: {str(e)}")
                last_error = str(e)
                if hasattr(e, 'exc_info') and e.exc_info and e.exc_info[1]:
                    last_error = str(e.exc_info[1]) # Get a more specific error message
                # Continue to next proxy
            except Exception as e:
                logger.error(f"Unexpected error with proxy {proxy_url if proxy_url else 'None'} for {url}: {str(e)}", exc_info=True)
                last_error = f"An unexpected error occurred: {str(e)}"
                # Continue to next proxy or fail if this was an unexpected issue not related to proxy

        if download_successful and downloaded_filename:
            return jsonify({
                'success': True,
                'filename': downloaded_filename
            })
        else:
            logger.error(f"All download attempts failed for {url}. Last error: {last_error}")
            return jsonify({'error': f'Download failed after trying all options: {last_error}'}), 500

    except Exception as e:
        logger.error(f"Critical error in download route for {url}: {str(e)}", exc_info=True)
        }

        if download_type == 'video' and quality != 'best':
            ydl_opts['format'] = f'bestvideo[height<={quality[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality[:-1]}]/best'
        elif download_type == 'audio':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        # This part is now handled by the proxy rotation loop above
        # Ensure the final return for general exceptions in the route is outside the loop logic
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

@app.route('/download_file/<filename>')
def download_file(filename):
    try:
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], filename),
            as_attachment=True,
            download_name=filename
        )
    except FileNotFoundError:
        logger.error(f"File not found for download: {filename}", exc_info=True) # Added exc_info
        return jsonify({'error': 'File not found. It might have been deleted or failed to save.'}), 404
    except Exception as e:
        logger.error(f"Error sending file {filename}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Could not send file: {str(e)}'}), 500

@app.route('/get_thumbnail')
def get_thumbnail():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        yt = YouTube(url)
        return jsonify({'thumbnail': yt.thumbnail_url})
    except Exception as e:
        logger.error(f"Error getting thumbnail for {url}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Could not retrieve thumbnail: {str(e)}'}), 500

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
        logger.error(f"Error processing get_video_info for {url}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Could not retrieve and save video details: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
