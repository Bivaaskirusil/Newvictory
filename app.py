import os
import json
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_file, Response
from bs4 import BeautifulSoup
import requests
import re
from datetime import datetime
import logging
import tempfile
import io

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s %(module)s.%(funcName)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB max file size
app.config['UPLOAD_FOLDER'] = 'downloads'

# Ensure download directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

# Proxies configuration (to be used with yt-dlp)
PROXIES = [
    'http://orukwgru:xhwbr7lu6jlf@198.23.239.134:6540',
    'http://orukwgru:xhwbr7lu6jlf@207.244.217.165:6712',
    'http://orukwgru:xhwbr7lu6jlf@107.172.163.27:6543',
    'http://orukwgru:xhwbr7lu6jlf@23.94.138.75:6349',
    'http://orukwgru:xhwbr7lu6jlf@216.10.27.159:6837',
    'http://orukwgru:xhwbr7lu6jlf@136.0.207.84:6661',
    'http://orukwgru:xhwbr7lu6jlf@64.64.118.149:6732',
    'http://orukwgru:xhwbr7lu6jlf@142.147.128.93:6593',
    'http://orukwgru:xhwbr7lu6jlf@104.239.105.125:6655',
    'http://orukwgru:xhwbr7lu6jlf@173.0.9.70:5653',
]

# COOKIE_FILE = 'youtube_cookies.txt' # No longer used directly by main user-facing functions

# Helper function to parse yt-dlp formats for video qualities
def parse_ytdlp_video_qualities(formats):
    qualities = set()
    for f in formats:
        # Ensure it's a video format, has height, and ideally mp4 container with both video and audio
        if f.get('vcodec') != 'none' and f.get('height') and f.get('ext') == 'mp4':
            # Prefer formats that also have audio for simpler selection, though frontend might combine later
            if f.get('acodec') != 'none': 
                qualities.add(f"{f.get('height')}p")
        # Fallback for some webm or other formats if mp4 with audio isn't common
        elif f.get('vcodec') != 'none' and f.get('height'):
             qualities.add(f"{f.get('height')}p (webm)") # Indicate if it's likely webm or needs muxing

    if not qualities and any(f.get('vcodec') != 'none' and f.get('height') for f in formats):
        # If no mp4 found, list any available video resolution
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('height'):
                 qualities.add(f"{f.get('height')}p")

    # Sort by resolution (integer part of '720p'), descending
    sorted_qualities = sorted(list(qualities), key=lambda x: int(x.split('p')[0]) if x.split('p')[0].isdigit() else 0, reverse=True)
    
    if not sorted_qualities and any(f.get('vcodec') != 'none' for f in formats):
        sorted_qualities.append('Best Video') # Generic fallback
    
    return sorted_qualities if sorted_qualities else ['Best Video']

@app.route('/get_info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    cookies_str = request.json.get('cookies')

    if not url:
        return jsonify({'error': 'URL is required'}), 400
    if not cookies_str:
        return jsonify({'error': 'YouTube cookies are required for this operation'}), 400

    temp_cookie_file_path = None

    try:
        # Create temp cookie file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as tmp_cookie:
            tmp_cookie.write(cookies_str)
            temp_cookie_file_path = tmp_cookie.name

        # All subsequent logic is now correctly indented within the try block
        ydl_opts_info = {
            'quiet': False,
            'no_warnings': False,
            'logger': logger, 
            'skip_download': True,
            'extract_flat': 'discard_in_playlist',
            'forcejson': True,
            'ignoreerrors': True, 
            'cookiefile': temp_cookie_file_path, # MODIFIED: Use the temporary cookie file
        }

        proxies_to_try = PROXIES + [None] if PROXIES else [None]
        last_error = "Failed to fetch video metadata after trying all available proxies."
        info_dict_full = None
        info_dict = None # Initialize info_dict here

        for proxy_url in proxies_to_try:
            current_ydl_opts = ydl_opts_info.copy()
            if proxy_url:
                current_ydl_opts['proxy'] = proxy_url
                logger.info(f"Attempting metadata fetch for {url} using proxy: {proxy_url}")
            else:
                current_ydl_opts.pop('proxy', None)
                logger.info(f"Attempting metadata fetch for {url} without proxy")
            
            try:
                with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                    info_dict_full = ydl.extract_info(url, download=False)
                    
                    if info_dict_full and 'entries' in info_dict_full and info_dict_full['entries']:
                        info_dict = info_dict_full['entries'][0]
                    elif info_dict_full:
                        info_dict = info_dict_full
                    else:
                        logger.warning(f"Metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) returned no data.")
                        last_error = "No data received from video provider."
                        info_dict_full = None 
                        info_dict = None
                        continue

                    if not info_dict.get('title') or info_dict.get('_type') == 'error':
                        err_msg = "Video information is unavailable (may be private, deleted, or restricted)."
                        if info_dict.get('_type') == 'error':
                            err_msg = info_dict.get('error_message', 'yt-dlp reported an error but no specific message.')
                            logger.warning(f"yt-dlp returned an error dictionary for {url} (proxy: {proxy_url if proxy_url else 'None'}): {json.dumps(info_dict)}")
                        elif info_dict.get('title') is None and info_dict.get('webpage_url_basename') == 'error':
                            err_msg = "Video information is unavailable (may be private or deleted)."
                        else: 
                            err_msg = "Received incomplete video information (e.g., no title)."
                        
                        logger.warning(f"Metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) returned incomplete data or error. Deduced Message: {err_msg}")
                        last_error = err_msg
                        info_dict_full = None 
                        info_dict = None
                        continue 

                    logger.info(f"Successfully fetched metadata for {url} with proxy: {proxy_url if proxy_url else 'None'}")
                    break 

            except yt_dlp.utils.DownloadError as e:
                logger.warning(f"yt-dlp DownloadError during metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}")
                last_error = str(e)
                if hasattr(e, 'exc_info') and e.exc_info and e.exc_info[1]:
                    last_error = str(e.exc_info[1])
                info_dict_full = None 
                info_dict = None
            except Exception as e:
                logger.error(f"Unexpected error during metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}", exc_info=True)
                last_error = f"An unexpected error occurred: {str(e)}"
                info_dict_full = None 
                info_dict = None
        
        if not info_dict_full or not info_dict: 
            logger.error(f"All metadata fetch attempts failed for {url}. Last error: {last_error}")
            pass

    finally:
        if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
            try:
                os.remove(temp_cookie_file_path)
                logger.debug(f"Temporary cookie file {temp_cookie_file_path} removed.")
            except Exception as e_rm:
                logger.error(f"Error removing temporary cookie file {temp_cookie_file_path}: {e_rm}")

    if not info_dict_full or not info_dict or not info_dict.get('title'):
        logger.error(f"All metadata fetch attempts failed for {url} (checked after finally). Last error: {last_error}")
        return jsonify({'error': f'Could not retrieve video information: {last_error}'}), 500

    title = info_dict.get('title', 'N/A')
    author = info_dict.get('uploader', info_dict.get('channel', 'N/A'))
    duration_seconds = info_dict.get('duration', 0)
    length_str = f"{duration_seconds // 60}:{str(duration_seconds % 60).zfill(2)}" if duration_seconds else "N/A"
    views = f"{info_dict.get('view_count', 0):,}" if info_dict.get('view_count') is not None else "N/A"
    
    upload_date_str = info_dict.get('upload_date') 
    publish_date_str = 'N/A'
    if upload_date_str:
        try:
            publish_date_dt = datetime.strptime(upload_date_str, '%Y%m%d')
            publish_date_str = publish_date_dt.strftime('%Y-%m-%d')
        except ValueError:
            logger.warning(f"Could not parse upload_date: {upload_date_str}")
            publish_date_str = upload_date_str 
    
    selected_thumbnail = info_dict.get('thumbnail') 
    if not selected_thumbnail and info_dict.get('thumbnails'):
        hq_thumb = next((t.get('url') for t in info_dict['thumbnails'] if 'hqdefault' in t.get('id', '') or 'hqdefault' in t.get('url', '')), None)
        if hq_thumb:
            selected_thumbnail = hq_thumb
        else:
            selected_thumbnail = info_dict['thumbnails'][-1].get('url') 
    if not selected_thumbnail:
         selected_thumbnail = 'static/placeholder.png' 

    available_qualities = parse_ytdlp_video_qualities(info_dict.get('formats', []))

    video_info_response = {
        'title': title,
        'author': author,
        'length': length_str,
        'views': views,
        'publish_date': publish_date_str,
        'thumbnail': selected_thumbnail,
        'qualities': available_qualities
    }
    return jsonify(video_info_response)
@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    cookies_str = data.get('cookies')
    quality = data.get('quality', 'best')
    download_type = data.get('type', 'video')

    if not url:
        return jsonify({'error': 'URL is required'}), 400
    if not cookies_str:
        return jsonify({'error': 'YouTube cookies are required for this operation'}), 400

    temp_cookie_file_path = None

    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_cookie:
            tmp_cookie.write(cookies_str)
            temp_cookie_file_path = tmp_cookie.name

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if download_type == 'video' else 'bestaudio/best',
            'outtmpl': os.path.join(app.config['UPLOAD_FOLDER'], '%(title)s.%(ext)s'),
            'noplaylist': True,
            'quiet': False, # Set to False to capture more error details
            'no_warnings': False, # Set to False to capture more error details
            'extract_flat': 'discard_in_playlist', # Avoids downloading playlist items if a single video URL from a playlist is given
            'skip_download': True, # We only want to extract info first to get title for filename
            'ignoreerrors': True, # Continue on download errors for individual formats
            'verbose': True, # More verbose output for debugging
            'cookiefile': temp_cookie_file_path,
        }

        # Initial info extraction to get the title for the filename template
        logger.debug(f"Initial ydl_opts for info extraction (in download): {ydl_opts}")
        base_title = 'untitled_video' # Default title
        last_error_dl = "Failed to download after trying all available proxies." # Initialize last_error_dl
        download_successful = False # Initialize download_successful
        downloaded_filename = None # Initialize downloaded_filename

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl_info_extractor: # ydl_opts has skip_download:True here
                info = ydl_info_extractor.extract_info(url, download=False)
                if info and info.get('title'):
                    base_title = info.get('title')
                logger.info(f"Successfully extracted video title for download: {base_title}")
        except Exception as e_info:
            logger.error(f"Initial info extraction failed for {url} during download prep: {str(e_info)}", exc_info=True)
            last_error_dl = f"Failed to fetch initial video metadata for filename: {str(e_info)}"
            # Proceed with default title, error will be returned if download fails

        def sanitize_filename(filename):
            return re.sub(r'[\\/*?:"<>|]', "_", filename)

        sanitized_title = sanitize_filename(base_title)
        ydl_opts['outtmpl'] = os.path.join(app.config['UPLOAD_FOLDER'], f'{sanitized_title}.%(ext)s')
        ydl_opts['skip_download'] = False # Crucial: Set to False for actual download

        if download_type == 'video' and quality != 'best' and quality.endswith('p'):
            quality_val = quality[:-1]
            ydl_opts['format'] = f'bestvideo[height<={quality_val}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<={quality_val}]/bestvideo[height<={quality_val}]+bestaudio/best[height<={quality_val}]'
        elif download_type == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        proxies_to_try = PROXIES + [None] if PROXIES else [None]
        final_filepath = None

        for proxy_url in proxies_to_try:
            if download_successful: break
            current_ydl_opts = ydl_opts.copy()
            if proxy_url:
                current_ydl_opts['proxy'] = proxy_url
                logger.info(f"Attempting download for {url} (type: {download_type}, quality: {quality}) using proxy: {proxy_url}")
            else:
                current_ydl_opts.pop('proxy', None)
                logger.info(f"Attempting download for {url} (type: {download_type}, quality: {quality}) without proxy")
            
            logger.debug(f"Current ydl_opts for download attempt: {current_ydl_opts}")
            try:
                with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                    download_info = ydl.extract_info(url, download=True)
                    
                    r_downloads = download_info.get('requested_downloads')
                    if r_downloads and len(r_downloads) > 0:
                        final_filepath = r_downloads[0].get('filepath')
                    elif download_info.get('filepath'): 
                         final_filepath = download_info.get('filepath')
                    else:
                        temp_filename_info = ydl.prepare_filename(download_info)
                        if download_type == 'audio' and not temp_filename_info.endswith('.mp3'):
                            final_filepath = os.path.splitext(temp_filename_info)[0] + '.mp3'
                            if not os.path.exists(final_filepath):
                                final_filepath = temp_filename_info 
                        else:
                            final_filepath = temp_filename_info
                    
                    if final_filepath and os.path.exists(final_filepath):
                        logger.info(f"Download successful with proxy {proxy_url if proxy_url else 'None'}. File path: {final_filepath}")
                        downloaded_filename = os.path.basename(final_filepath)
                        download_successful = True
                        break 
                    else:
                        logger.warning(f"Download attempt with proxy {proxy_url if proxy_url else 'None'} seemed to complete but file not found at {final_filepath}")
                        last_error_dl = "Download process completed but output file was not found."
            except yt_dlp.utils.DownloadError as e_dl:
                logger.warning(f"Download failed with proxy {proxy_url if proxy_url else 'None'} for {url}: {str(e_dl)}")
                last_error_dl = str(e_dl)
                if hasattr(e_dl, 'exc_info') and e_dl.exc_info and e_dl.exc_info[1]:
                    last_error_dl = str(e_dl.exc_info[1])
            except Exception as e_gen:
                logger.error(f"Unexpected error with proxy {proxy_url if proxy_url else 'None'} for {url}: {str(e_gen)}", exc_info=True)
                last_error_dl = f"An unexpected error occurred: {str(e_gen)}"
        
        # End of proxy loop. download_successful, downloaded_filename, last_error_dl are set.
        # The main try block for cookie file management continues here.


    finally:
        if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
            try:
                os.remove(temp_cookie_file_path)
                logger.debug(f"Temporary cookie file {temp_cookie_file_path} removed for download.")
            except Exception as e_rm:
                logger.error(f"Error removing temporary cookie file {temp_cookie_file_path} for download: {e_rm}")

    # This is after the 'finally' for cookie cleanup, part of the main 'try' for the route
    if download_successful and downloaded_filename:
        return jsonify({
            'success': True,
            'filename': downloaded_filename
        })
    else:
        # If last_error_dl was not updated by specific errors, it retains its initial value
        return jsonify({'error': f'Failed to download {download_type}: {last_error_dl}'}), 500

# The main 'except Exception as e_route:' for the whole route, if needed, would be outside this structure
# For now, assuming specific errors are caught or Flask handles others.



@app.route('/get_thumbnail', methods=['POST'])
def get_thumbnail():
    url = request.json.get('url')
    cookies_str = request.json.get('cookies')

    if not url:
        return jsonify({'error': 'URL is required'}), 400
    if not cookies_str:
        return jsonify({'error': 'YouTube cookies are required for this operation'}), 400

    temp_cookie_file_path = None
    selected_thumbnail_url = None
    last_error_thumb = "Failed to fetch thumbnail URL after trying all available proxies."

    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_cookie:
            tmp_cookie.write(cookies_str)
            temp_cookie_file_path = tmp_cookie.name

        ydl_opts_thumb = {
            'quiet': False,
            'no_warnings': False,
            'logger': logger,
            'skip_download': True,
            'extract_flat': 'discard_in_playlist',
            'forcejson': True,
            'ignoreerrors': True,
            'cookiefile': temp_cookie_file_path,
        }

        proxies_to_try = PROXIES + [None] if PROXIES else [None]
        info_dict = None # To store the relevant part of info_dict_full

        for proxy_url in proxies_to_try:
            current_ydl_opts = ydl_opts_thumb.copy()
            if proxy_url:
                current_ydl_opts['proxy'] = proxy_url
                logger.info(f"Attempting thumbnail URL fetch for {url} using proxy: {proxy_url}")
            else:
                current_ydl_opts.pop('proxy', None)
                logger.info(f"Attempting thumbnail URL fetch for {url} without proxy")
            
            try:
                with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                    info_dict_full = ydl.extract_info(url, download=False)
                    
                    if info_dict_full and 'entries' in info_dict_full and info_dict_full['entries']:
                        info_dict = info_dict_full['entries'][0]
                    elif info_dict_full:
                        info_dict = info_dict_full
                    else:
                        last_error_thumb = "No information returned by yt-dlp."
                        info_dict = None # Ensure loop continues or fails gracefully
                        continue

                    if not info_dict or not info_dict.get('title') or info_dict.get('_type') == 'error':
                        err_msg = "Video information for thumbnail is unavailable (may be private, deleted, or restricted)."
                        if info_dict and info_dict.get('_type') == 'error':
                            err_msg = info_dict.get('error', err_msg)
                        last_error_thumb = err_msg
                        logger.warning(f"Failed to get valid video info for thumbnail from {url} (proxy: {proxy_url if proxy_url else 'None'}): {err_msg}")
                        info_dict = None # Mark as failure for this proxy
                        continue

                    # Thumbnail selection logic (similar to get_info)
                    thumb_url = info_dict.get('thumbnail') # Often the best one
                    if not thumb_url and info_dict.get('thumbnails'):
                        hq_thumb = next((t.get('url') for t in info_dict['thumbnails'] if 'hqdefault' in t.get('id', '') or 'hqdefault' in t.get('url', '')), None)
                        if hq_thumb:
                            thumb_url = hq_thumb
                        elif info_dict['thumbnails']:
                            thumb_url = info_dict['thumbnails'][-1].get('url')
                    
                    if thumb_url:
                        selected_thumbnail_url = thumb_url
                        logger.info(f"Successfully fetched thumbnail URL for {url} with proxy: {proxy_url if proxy_url else 'None'}")
                        break # Success
                    else:
                        last_error_thumb = "No thumbnail URL found in video metadata."
                        # Continue to next proxy

            except yt_dlp.utils.DownloadError as e_dl:
                logger.warning(f"yt-dlp DownloadError during thumbnail URL fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e_dl)}")
                last_error_thumb = str(e_dl)
                if hasattr(e_dl, 'exc_info') and e_dl.exc_info and e_dl.exc_info[1]:
                    last_error_thumb = str(e_dl.exc_info[1])
            except Exception as e_gen:
                logger.error(f"Unexpected error during thumbnail URL fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e_gen)}", exc_info=True)
                last_error_thumb = f"An unexpected error occurred: {str(e_gen)}"
                # Continue to next proxy

        if not selected_thumbnail_url:
            logger.error(f"All attempts to fetch thumbnail URL failed for {url}. Last error: {last_error_thumb}")
            return jsonify({'error': f'Could not retrieve thumbnail URL: {last_error_thumb}'}), 500

        # Download the thumbnail image
        logger.info(f"Downloading thumbnail from URL: {selected_thumbnail_url}")
        response = requests.get(selected_thumbnail_url, stream=True)
        if response.status_code == 200:
            # Determine content type, default to jpeg
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            # Sanitize filename from URL or use a default
            filename_base = info_dict.get('title', 'thumbnail')
            sanitized_title = re.sub(r'[^\w\-_\.]', '_', filename_base)
            ext = content_type.split('/')[-1] if '/' in content_type else 'jpg'
            download_name = f"{sanitized_title}_thumbnail.{ext}"

            return send_file(
                io.BytesIO(response.content),
                mimetype=content_type,
                as_attachment=True,
                download_name=download_name
            )
        else:
            logger.error(f"Failed to download thumbnail image from {selected_thumbnail_url}. Status: {response.status_code}")
            return jsonify({'error': f'Failed to download thumbnail image. Status: {response.status_code}'}), 500

    except Exception as e_route:
        logger.error(f"Error in /get_thumbnail route for {url}: {str(e_route)}", exc_info=True)
        return jsonify({'error': f'An internal error occurred: {str(e_route)}'}), 500
    finally:
        if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
            try:
                os.remove(temp_cookie_file_path)
                logger.debug(f"Temporary cookie file {temp_cookie_file_path} removed for get_thumbnail.")
            except Exception as e_rm:
                logger.error(f"Error removing temporary cookie file {temp_cookie_file_path} for get_thumbnail: {e_rm}")



@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    url = request.json.get('url')
    cookies_str = request.json.get('cookies')

    if not url:
        return jsonify({'error': 'URL is required'}), 400
    if not cookies_str:
        return jsonify({'error': 'YouTube cookies are required for this operation'}), 400

    temp_cookie_file_path = None
    temp_info_file_path = None
    last_error_info_file = "Failed to fetch video metadata for text file after trying all available proxies."
    info_dict_final = None # To store the successfully fetched info_dict

    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_cookie:
            tmp_cookie.write(cookies_str)
            temp_cookie_file_path = tmp_cookie.name

        # ydl_opts for fetching full metadata (similar to get_info)
        ydl_opts_full_info = {
            'quiet': False,
            'no_warnings': False,
            'logger': logger,
            'skip_download': True,
            'extract_flat': 'discard_in_playlist', # Important for single video from playlist
            'forcejson': True,
            'ignoreerrors': True, # Try to get as much info as possible
            'cookiefile': temp_cookie_file_path,
            'dump_single_json': True, # Ensures we get a JSON string even for playlists (for the first item)
            'playlist_items': '1', # Only process the first item if it's a playlist URL
        }

        proxies_to_try = PROXIES + [None] if PROXIES else [None]

        for proxy_url in proxies_to_try:
            current_ydl_opts = ydl_opts_full_info.copy()
            if proxy_url:
                current_ydl_opts['proxy'] = proxy_url
                logger.info(f"Attempting full metadata fetch for info file {url} using proxy: {proxy_url}")
            else:
                current_ydl_opts.pop('proxy', None)
                logger.info(f"Attempting full metadata fetch for info file {url} without proxy")
            
            try:
                with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                    # extract_info with download=False and dump_single_json=True should give a dict
                    # if it's a single video, or a dict of the first item if it's a playlist.
                    extracted_data = ydl.extract_info(url, download=False)

                    # Determine if we got data for a single video or the first item of a playlist
                    if extracted_data and 'entries' in extracted_data and extracted_data['entries']:
                        # It's a playlist, use the first entry
                        info_dict_final = extracted_data['entries'][0]
                    elif extracted_data and extracted_data.get('title'):
                        # It's a single video's data
                        info_dict_final = extracted_data
                    else:
                        # No valid data or error type
                        err_msg = "No valid video information returned by yt-dlp."
                        if extracted_data and extracted_data.get('_type') == 'error':
                           err_msg = extracted_data.get('error', err_msg)
                        last_error_info_file = err_msg
                        logger.warning(f"Failed to get valid video info for text file from {url} (proxy: {proxy_url if proxy_url else 'None'}): {err_msg}")
                        info_dict_final = None # Mark as failure for this proxy
                        continue # Try next proxy

                    # Check if essential fields like title are present
                    if not info_dict_final.get('title'):
                        last_error_info_file = "Video information is incomplete (missing title)."
                        logger.warning(f"{last_error_info_file} (proxy: {proxy_url if proxy_url else 'None'})")
                        info_dict_final = None # Mark as failure
                        continue # Try next proxy
                    
                    logger.info(f"Successfully fetched full metadata for info file {url} with proxy: {proxy_url if proxy_url else 'None'}")
                    break # Success

            except yt_dlp.utils.DownloadError as e_dl:
                logger.warning(f"yt-dlp DownloadError during full metadata fetch for info file {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e_dl)}")
                last_error_info_file = str(e_dl)
                if hasattr(e_dl, 'exc_info') and e_dl.exc_info and e_dl.exc_info[1]:
                    last_error_info_file = str(e_dl.exc_info[1])
                info_dict_final = None
            except Exception as e_gen:
                logger.error(f"Unexpected error during full metadata fetch for info file {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e_gen)}", exc_info=True)
                last_error_info_file = f"An unexpected error occurred: {str(e_gen)}"
                info_dict_final = None
        
        if not info_dict_final:
            logger.error(f"All attempts to fetch full metadata for info file failed for {url}. Last error: {last_error_info_file}")
            return jsonify({'error': f'Could not retrieve video information for text file: {last_error_info_file}'}), 500

        # Format info_dict_final into a string
        info_text_content = []
        info_text_content.append(f"Title: {info_dict_final.get('title', 'N/A')}")
        info_text_content.append(f"Author: {info_dict_final.get('uploader', 'N/A')} ({info_dict_final.get('uploader_url', 'N/A')})")
        info_text_content.append(f"Video ID: {info_dict_final.get('id', 'N/A')}")
        info_text_content.append(f"Original URL: {info_dict_final.get('webpage_url', url)}")
        duration_sec = info_dict_final.get('duration')
        if duration_sec:
            info_text_content.append(f"Duration: {datetime.utcfromtimestamp(duration_sec).strftime('%H:%M:%S') if duration_sec > 0 else 'N/A'}")
        else:
            info_text_content.append(f"Duration: {info_dict_final.get('duration_string', 'N/A')}")
        upload_date_str = info_dict_final.get('upload_date', 'N/A') # YYYYMMDD
        if upload_date_str != 'N/A':
            try:
                publish_date_dt = datetime.strptime(upload_date_str, '%Y%m%d')
                info_text_content.append(f"Publish Date: {publish_date_dt.strftime('%Y-%m-%d')}")
            except ValueError:
                info_text_content.append(f"Publish Date: {upload_date_str} (raw)")
        else:
            info_text_content.append(f"Publish Date: N/A")
        info_text_content.append(f"View Count: {info_dict_final.get('view_count', 'N/A'):,}")
        info_text_content.append(f"Like Count: {info_dict_final.get('like_count', 'N/A'):,}")
        info_text_content.append(f"Description:\n{info_dict_final.get('description', 'N/A')}")
        info_text_content.append(f"\n--- Available Formats ---")
        for f_format in info_dict_final.get('formats', []):
            info_text_content.append(f"  ID: {f_format.get('format_id', 'N/A')}, Ext: {f_format.get('ext', 'N/A')}, Resolution: {f_format.get('format_note', f_format.get('resolution', 'N/A'))}, Codecs: v:{f_format.get('vcodec', 'none')}, a:{f_format.get('acodec', 'none')}")
        
        info_string = "\n".join(info_text_content)

        # Sanitize filename
        filename_base = info_dict_final.get('title', 'video_info')
        sanitized_title = re.sub(r'[^\w\-_\.]', '_', filename_base)
        filename_txt = f"{sanitized_title}_info.txt"

        # Write to a temporary text file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt', dir=app.config['UPLOAD_FOLDER']) as tmp_info_file:
            tmp_info_file.write(info_string)
            temp_info_file_path = tmp_info_file.name
        
        logger.info(f"Video info text file created: {temp_info_file_path}")
        return send_file(temp_info_file_path, as_attachment=True, download_name=filename_txt, mimetype='text/plain')

    except Exception as e_route:
        logger.error(f"Error in /get_video_info route for {url}: {str(e_route)}", exc_info=True)
        return jsonify({'error': f'An internal error occurred: {str(e_route)}'}), 500
    finally:
        if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
            try:
                os.remove(temp_cookie_file_path)
                logger.debug(f"Temporary cookie file {temp_cookie_file_path} removed for get_video_info.")
            except Exception as e_rm_cookie:
                logger.error(f"Error removing temporary cookie file {temp_cookie_file_path} for get_video_info: {e_rm_cookie}")
        # temp_info_file_path is in UPLOAD_FOLDER and send_file should handle it, 
        # but if send_file fails before completion or an error occurs before send_file, it might be orphaned.
        # For robust cleanup, especially if send_file is not guaranteed to consume/delete:
        if temp_info_file_path and os.path.exists(temp_info_file_path):
             try:
                 os.remove(temp_info_file_path)
                 logger.debug(f"Temporary info file {temp_info_file_path} removed after attempt to send.")
             except Exception as e_rm_info:
                 logger.error(f"Error removing temporary info file {temp_info_file_path}: {e_rm_info}")


if __name__ == '__main__':
    app.run(debug=True, port=5000)
