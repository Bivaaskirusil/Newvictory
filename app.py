import os
import json
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_file, Response
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

COOKIE_FILE = 'youtube_cookies.txt'

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
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    ydl_opts_info = {
        'quiet': False,
        'no_warnings': False,
        'logger': logger, 
        'skip_download': True,
        'extract_flat': 'discard_in_playlist',
        'forcejson': True,
        'ignoreerrors': True, # Try to fetch info even if some parts (like comments) fail
        'cookiefile': COOKIE_FILE,
        # 'youtube_include_dash_manifest': False, # Might reduce unnecessary data for info extraction
    }

    proxies_to_try = PROXIES + [None] if PROXIES else [None]
    last_error = "Failed to fetch video metadata after trying all available proxies."
    info_dict_full = None

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
                
                # If 'entries' is present, it's a playlist, take the first video's info
                # Or handle as error/unsupported if only single video expected
                if info_dict_full and 'entries' in info_dict_full and info_dict_full['entries']:
                    info_dict = info_dict_full['entries'][0]
                elif info_dict_full:
                    info_dict = info_dict_full
                else:
                    # If ydl.extract_info returned None or an empty dict for some reason
                    logger.warning(f"Metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) returned no data.")
                    last_error = "No data received from video provider."
                    info_dict_full = None # Ensure loop continues
                    continue

                # Check if essential fields like title are present, otherwise it might be an error page or restricted video
                if not info_dict.get('title') or info_dict.get('_type') == 'error':
                    err_msg = "Video information is unavailable (may be private, deleted, or restricted)."
                    if info_dict.get('_type') == 'error':
                        err_msg = info_dict.get('error_message', 'yt-dlp reported an error but no specific message.')
                        logger.warning(f"yt-dlp returned an error dictionary for {url} (proxy: {proxy_url if proxy_url else 'None'}): {json.dumps(info_dict)}")
                    elif info_dict.get('title') is None and info_dict.get('webpage_url_basename') == 'error':
                        err_msg = "Video information is unavailable (may be private or deleted)."
                    else: # No title, but not explicitly an error type from ytdlp
                        err_msg = "Received incomplete video information (e.g., no title)."
                    
                    logger.warning(f"Metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) returned incomplete data or error. Deduced Message: {err_msg}")
                    last_error = err_msg
                    info_dict_full = None # Mark as failure for this proxy
                    continue # Try next proxy

                logger.info(f"Successfully fetched metadata for {url} with proxy: {proxy_url if proxy_url else 'None'}")
                break # Success, info_dict_full contains the data (or info_dict if playlist item)

        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"yt-dlp DownloadError during metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}")
            last_error = str(e)
            if hasattr(e, 'exc_info') and e.exc_info and e.exc_info[1]:
                last_error = str(e.exc_info[1])
            info_dict_full = None # Mark as failure
            # Continue to next proxy
        except Exception as e:
            logger.error(f"Unexpected error during metadata fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}", exc_info=True)
            last_error = f"An unexpected error occurred: {str(e)}"
            info_dict_full = None # Mark as failure
            # Continue to next proxy

    if not info_dict_full or not info_dict_full.get('title'): # Check final result after loop
        logger.error(f"All metadata fetch attempts failed for {url}. Last error: {last_error}")
        return jsonify({'error': f'Could not retrieve video information: {last_error}'}), 500

    # Use 'info_dict' which points to the single video's data (either original or first playlist item)
    # If info_dict_full had 'entries', info_dict is info_dict_full['entries'][0]
    # Otherwise, info_dict is info_dict_full itself.
    # This logic was handled above, so 'info_dict' should be the correct one here.
    
    # Safely extract and format data
    title = info_dict.get('title', 'N/A')
    author = info_dict.get('uploader', info_dict.get('channel', 'N/A'))
    duration_seconds = info_dict.get('duration', 0)
    length_str = f"{duration_seconds // 60}:{str(duration_seconds % 60).zfill(2)}" if duration_seconds else "N/A"
    views = f"{info_dict.get('view_count', 0):,}" if info_dict.get('view_count') is not None else "N/A"
    
    upload_date_str = info_dict.get('upload_date') # Format YYYYMMDD
    publish_date_str = 'N/A'
    if upload_date_str:
        try:
            publish_date_dt = datetime.strptime(upload_date_str, '%Y%m%d')
            publish_date_str = publish_date_dt.strftime('%Y-%m-%d')
        except ValueError:
            logger.warning(f"Could not parse upload_date: {upload_date_str}")
            publish_date_str = upload_date_str # Use raw if parsing fails

    # Thumbnail: yt-dlp provides a list of thumbnails, find a good one or use the default
    selected_thumbnail = info_dict.get('thumbnail') # This is often the best one
    if not selected_thumbnail and info_dict.get('thumbnails'):
        # Prefer thumbnails with 'hqdefault' in id or url, or just take the last one (often highest res)
        hq_thumb = next((t.get('url') for t in info_dict['thumbnails'] if 'hqdefault' in t.get('id', '') or 'hqdefault' in t.get('url', '')), None)
        if hq_thumb:
            selected_thumbnail = hq_thumb
        else:
            selected_thumbnail = info_dict['thumbnails'][-1].get('url') # Fallback to last in list
    if not selected_thumbnail:
         selected_thumbnail = 'static/placeholder.png' # A default placeholder

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
    quality = data.get('quality', 'best')
    download_type = data.get('type', 'video')  # 'video' or 'audio'
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if download_type == 'video' else 'bestaudio/best',
            'outtmpl': os.path.join(app.config['UPLOAD_FOLDER'], '%(title)s.%(ext)s'),
            'noplaylist': True,
                    # Proxy will be handled in the loop
            'quiet': False, # Set to False to capture more error details
            'no_warnings': False, # Set to False to capture more error details
            'extract_flat': 'discard_in_playlist', # Avoids downloading playlist items if a single video URL from a playlist is given
            'skip_download': True, # We only want to extract info first to get title for filename
            'ignoreerrors': True, # Continue on download errors for individual formats
            'verbose': True # More verbose output for debugging
        }

        # Refine format based on specific quality or audio type
        if download_type == 'video' and quality != 'best':
            # Override format for specific video quality that prefers mp4 container.
            ydl_opts['format'] = f'bestvideo[height<={quality[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<={quality[:-1]}]/bestvideo[height<={quality[:-1]}]+bestaudio/best[height<={quality[:-1]}]'
            ydl_opts.pop('postprocessors', None) # Ensure no audio postprocessors conflict
        elif download_type == 'audio':
            # Ensure format is set for best audio and add MP3 postprocessing
            # The default format in ydl_opts for audio is 'bestaudio/best', this confirms and adds postprocessor.
            ydl_opts['format'] = 'bestaudio/best' 
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        # If download_type == 'video' and quality == 'best', the initial format from ydl_opts definition is used.

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
        return jsonify({'error': f'An unexpected error occurred during download processing: {str(e)}'}), 500

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

    ydl_opts_thumb = {
        'quiet': False,
        'no_warnings': False,
        'logger': logger,
        'skip_download': True,
        'extract_flat': 'discard_in_playlist',
        'forcejson': True,
        'ignoreerrors': True,
        'cookiefile': COOKIE_FILE,
        # yt-dlp fetches standard metadata including thumbnails by default
    }

    proxies_to_try = PROXIES + [None] if PROXIES else [None]
    last_error = "Failed to fetch thumbnail after trying all available proxies."
    info_dict_full = None # To store the full result from ydl.extract_info
    info_dict = None # To store the actual video info (handles playlists)

    for proxy_url in proxies_to_try:
        current_ydl_opts = ydl_opts_thumb.copy()
        if proxy_url:
            current_ydl_opts['proxy'] = proxy_url
            logger.info(f"Attempting thumbnail fetch for {url} using proxy: {proxy_url}")
        else:
            current_ydl_opts.pop('proxy', None)
            logger.info(f"Attempting thumbnail fetch for {url} without proxy")
        
        try:
            with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                info_dict_full = ydl.extract_info(url, download=False)
                
                if info_dict_full and 'entries' in info_dict_full and info_dict_full['entries']:
                    info_dict = info_dict_full['entries'][0]
                elif info_dict_full:
                    info_dict = info_dict_full
                else:
                    logger.warning(f"Thumbnail fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) returned no data.")
                    last_error = "No data received for thumbnail."
                    info_dict_full = None # Reset to ensure loop continues or fails correctly
                    continue

                # Check if thumbnail information is present
                if info_dict.get('_type') == 'error' or (not info_dict.get('thumbnail') and not info_dict.get('thumbnails')):
                    err_msg = "Thumbnail is unavailable."
                    if info_dict.get('_type') == 'error':
                        err_msg = info_dict.get('error_message', 'yt-dlp reported an error regarding thumbnail but no specific message.')
                        logger.warning(f"yt-dlp returned an error dictionary during thumbnail fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {json.dumps(info_dict)}")
                    else: # No thumbnail fields found, but not an explicit ytdlp error type
                        err_msg = "No thumbnail information found in metadata."
                    logger.warning(f"Thumbnail fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) problematic. Deduced Message: {err_msg}")
                    last_error = err_msg
                    info_dict_full = None # Reset
                    continue
                
                logger.info(f"Successfully fetched thumbnail info for {url} with proxy: {proxy_url if proxy_url else 'None'}")
                break # Success

        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"yt-dlp DownloadError during thumbnail fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}")
            last_error = str(e)
            if hasattr(e, 'exc_info') and e.exc_info and e.exc_info[1]:
                last_error = str(e.exc_info[1])
            info_dict_full = None # Reset
        except Exception as e:
            logger.error(f"Unexpected error during thumbnail fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}", exc_info=True)
            last_error = f"An unexpected error occurred: {str(e)}"
            info_dict_full = None # Reset

    if not info_dict_full: # Check if loop completed without success
        logger.error(f"All thumbnail fetch attempts failed for {url}. Last error: {last_error}")
        return jsonify({'error': f'Could not retrieve thumbnail: {last_error}'}), 500

    # At this point, info_dict should hold the correct video metadata dictionary
    selected_thumbnail = info_dict.get('thumbnail') # yt-dlp often provides a direct 'thumbnail' field
    if not selected_thumbnail and info_dict.get('thumbnails'):
        # Fallback: iterate through thumbnails list to find a suitable one (e.g., hqdefault)
        hq_thumb = next((t.get('url') for t in info_dict['thumbnails'] if 'hqdefault' in t.get('id', '').lower() or 'hqdefault' in t.get('url', '').lower()), None)
        if hq_thumb:
            selected_thumbnail = hq_thumb
        elif info_dict['thumbnails']: # If no hqdefault, take the last one (often best quality)
            selected_thumbnail = info_dict['thumbnails'][-1].get('url')
    
    if not selected_thumbnail:
        logger.warning(f"No suitable thumbnail found for {url} in fetched metadata.")
        # Fallback to a placeholder if absolutely no thumbnail is found by yt-dlp
        # return jsonify({'error': 'No suitable thumbnail found in video metadata.'}), 404
        selected_thumbnail = 'static/placeholder.png' # Or return error as above

    return jsonify({'thumbnail': selected_thumbnail})


@app.route('/get_video_info')
def get_video_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    ydl_opts_details = {
        'quiet': False,
        'no_warnings': False,
        'logger': logger,
        'skip_download': True,
        'extract_flat': 'discard_in_playlist',
        'forcejson': True,
        'ignoreerrors': True,
        'cookiefile': COOKIE_FILE,
    }

    proxies_to_try = PROXIES + [None] if PROXIES else [None]
    last_error = "Failed to fetch detailed video info after trying all available proxies."
    info_dict_full = None
    info_dict = None # To store the actual video info (handles playlists)

    for proxy_url in proxies_to_try:
        current_ydl_opts = ydl_opts_details.copy()
        if proxy_url:
            current_ydl_opts['proxy'] = proxy_url
            logger.info(f"Attempting detailed info fetch for {url} using proxy: {proxy_url}")
        else:
            current_ydl_opts.pop('proxy', None)
            logger.info(f"Attempting detailed info fetch for {url} without proxy")
        
        try:
            with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                info_dict_full = ydl.extract_info(url, download=False)
                
                if info_dict_full and 'entries' in info_dict_full and info_dict_full['entries']:
                    info_dict = info_dict_full['entries'][0]
                elif info_dict_full:
                    info_dict = info_dict_full
                else:
                    logger.warning(f"Detailed info fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) returned no data.")
                    last_error = "No data received for detailed info."
                    info_dict_full = None
                    continue

                if info_dict.get('_type') == 'error' or not info_dict.get('title'):
                    err_msg = "Detailed video information is unavailable."
                    if info_dict.get('_type') == 'error':
                        err_msg = info_dict.get('error_message', 'yt-dlp reported an error for detailed info but no specific message.')
                        logger.warning(f"yt-dlp returned an error dictionary during detailed info fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {json.dumps(info_dict)}")
                    else: # No title, but not an explicit ytdlp error type
                        err_msg = "Received incomplete detailed video information (e.g., no title)."
                    logger.warning(f"Detailed info fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}) problematic. Deduced Message: {err_msg}")
                    last_error = err_msg
                    info_dict_full = None
                    continue
                
                logger.info(f"Successfully fetched detailed info for {url} with proxy: {proxy_url if proxy_url else 'None'}")
                break # Success

        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"yt-dlp DownloadError during detailed info fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}")
            last_error = str(e)
            if hasattr(e, 'exc_info') and e.exc_info and e.exc_info[1]:
                last_error = str(e.exc_info[1])
            info_dict_full = None
        except Exception as e:
            logger.error(f"Unexpected error during detailed info fetch for {url} (proxy: {proxy_url if proxy_url else 'None'}): {str(e)}", exc_info=True)
            last_error = f"An unexpected error occurred: {str(e)}"
            info_dict_full = None

    if not info_dict_full or not (info_dict and info_dict.get('title')): # Check after loop, ensure info_dict is valid
        logger.error(f"All detailed info fetch attempts failed for {url}. Last error: {last_error}")
        return jsonify({'error': f'Could not retrieve detailed video information: {last_error}'}), 500

    # Prepare information for the text file from info_dict
    title = info_dict.get('title', 'N/A')
    author = info_dict.get('uploader', info_dict.get('channel', 'N/A'))
    duration_seconds = info_dict.get('duration', 0)
    length_str = f"{duration_seconds // 60}:{str(duration_seconds % 60).zfill(2)}" if duration_seconds else "N/A"
    views = f"{info_dict.get('view_count', 0):,}" if info_dict.get('view_count') is not None else "N/A"
    upload_date_str = info_dict.get('upload_date') # Format YYYYMMDD
    publish_date_str = 'N/A'
    if upload_date_str:
        try:
            publish_date_dt = datetime.strptime(upload_date_str, '%Y%m%d')
            publish_date_str = publish_date_dt.strftime('%Y-%m-%d')
        except ValueError:
            logger.warning(f"Could not parse upload_date: {upload_date_str} for {title}")
            publish_date_str = upload_date_str # Use raw if parsing fails

    description = info_dict.get('description', 'N/A')
    tags = ', '.join(info_dict.get('tags', [])) if info_dict.get('tags') else 'N/A'
    age_limit = info_dict.get('age_limit')
    age_restricted_str = f"{age_limit}+" if age_limit and age_limit > 0 else "No"
    channel_url_val = info_dict.get('channel_url', 'N/A') # Renamed to avoid conflict
    webpage_url = info_dict.get('webpage_url', url)
    average_rating = info_dict.get('average_rating')
    average_rating_str = f"{average_rating:.2f}/5" if average_rating is not None else "N/A"
    like_count_val = f"{info_dict.get('like_count', 0):,}" if info_dict.get('like_count') is not None else "N/A" # Renamed

    text_file_info = {
        'Title': title,
        'Author': author,
        'Duration': length_str,
        'Views': views,
        'Publish Date': publish_date_str,
        'Description Preview': description.split('\n')[0][:200] + ('...' if len(description.split('\n')[0]) > 200 or '\n' in description else ''),
        'Full Description': description,
        'Tags/Keywords': tags,
        'Average Rating': average_rating_str,
        'Like Count': like_count_val,
        'Age Restricted': age_restricted_str,
        'Channel URL': channel_url_val,
        'Video URL': webpage_url,
    }
    
    sanitized_title = sanitize_filename(title)
    filename_txt = f"{sanitized_title}_info.txt"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename_txt)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            for key, value in text_file_info.items():
                f.write(f"{key}: {value}\n\n") # Added extra newline for readability

        return send_file(filepath, as_attachment=True, download_name=filename_txt)
    except Exception as e:
        logger.error(f"Error writing or sending video info text file for {url}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Could not generate or send video info text file: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
