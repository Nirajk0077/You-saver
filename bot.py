import os
import glob
import time
import asyncio
import re
import functools
import shutil
import json
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from yt_dlp import YoutubeDL
from config import Config

# Initialize the Client
app = Client(
    "youtube_downloader_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# Global States
# user_settings = { user_id: {'leech': bool} }
user_settings = {}
# user_data = { user_id: {'state': str, 'url': str, 'title': str, 'rename': str, 'thumb_path': str, 'original_message_id': int, 'quality': str} }
user_data = {}

def get_user_setting(user_id, key, default):
    if user_id not in user_settings:
        user_settings[user_id] = {}
    return user_settings[user_id].get(key, default)

def set_user_setting(user_id, key, value):
    if user_id not in user_settings:
        user_settings[user_id] = {}
    user_settings[user_id][key] = value

def progress_hook(d):
    if d['status'] == 'finished':
        print('Download finished, now converting ...')

def download_media_sync(url, output_path, quality, writethumbnail=True, mode='video'):
    """
    Synchronous wrapper for yt-dlp download to be run in an executor.
    mode: 'video' or 'audio'
    quality: '1080', '720' etc for video; '128', '320' etc for audio.
    """
    ydl_opts = {
        'outtmpl': output_path,
        'writethumbnail': writethumbnail,
        'quiet': True,
        'progress_hooks': [progress_hook],
        'noplaylist': True,
    }

    if mode == 'audio':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': quality,
            }],
        })
    else:
        # Default to 1080 if invalid video quality
        if quality not in ['1080', '720', '480', '360']:
            quality = '1080'
        
        format_str = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'
        ydl_opts.update({
            'format': format_str,
            'merge_output_format': 'mp4',
        })

    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
    
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return info

def fetch_info_sync(url):
    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
    }

    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'

    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def convert_to_netscape(content):
    """
    Detects format and converts to Netscape format string.
    Supported: Netscape, JSON, Header String.
    """
    # 1. Check if already Netscape (basic check)
    if content.startswith("# Netscape") or "\tTRUE\t" in content or "\tFALSE\t" in content:
        return content

    # 2. Check if JSON
    try:
        json_data = json.loads(content)
        if isinstance(json_data, list):
            netscape_lines = ["# Netscape HTTP Cookie File"]
            for cookie in json_data:
                domain = cookie.get('domain', '.youtube.com')
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = cookie.get('path', '/')
                secure = "TRUE" if cookie.get('secure', False) else "FALSE"
                expiration = int(cookie.get('expirationDate', time.time() + 31536000))
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                
                netscape_lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}")
            return "\n".join(netscape_lines)
    except json.JSONDecodeError:
        pass

    # 3. Check if Header String (key=value; key=value)
    if '=' in content and ';' in content:
        netscape_lines = ["# Netscape HTTP Cookie File"]
        pairs = content.split(';')
        for pair in pairs:
            if '=' in pair:
                key, value = pair.strip().split('=', 1)
                # Default values for header cookies
                domain = ".youtube.com"
                flag = "TRUE"
                path = "/"
                secure = "FALSE"
                expiration = int(time.time() + 31536000) # 1 year
                netscape_lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{key}\t{value}")
        return "\n".join(netscape_lines)

    # Fallback: return as is, maybe it's valid in a way we didn't check
    return content

@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    leech_status = "✅ ON" if get_user_setting(user_id, 'leech', False) else "❌ OFF"
    
    text = (
        f"👋 Hello {message.from_user.mention}!\n\n"
        "I am a YouTube Downloader Bot.\n"
        "Send me a YouTube link to download video or audio.\n\n"
        f"**Current Mode:**\nLeech Mode: {leech_status}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ])
    
    await message.reply_text(text, reply_markup=buttons)

@app.on_message(filters.command("set_cookies") & filters.private)
async def set_cookies_command(client: Client, message: Message):
    await message.reply_text(
        "🍪 **Set Cookies**\n\n"
        "Please send your cookies in one of the following formats:\n"
        "1. **Netscape Format** (File)\n"
        "2. **JSON Format** (File/Text)\n"
        "3. **Header String** (Text)\n\n"
        "Send the file or text now."
    )
    user_data[message.from_user.id] = {'state': 'waiting_cookies'}

@app.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data
    
    if data == "settings":
        is_leech = get_user_setting(user_id, 'leech', False)
        status_text = "✅ ON" if is_leech else "❌ OFF"
        btn_text = "Disable Leech Mode" if is_leech else "Enable Leech Mode"
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_text, callback_data="toggle_leech")],
            [InlineKeyboardButton("🍪 Set Cookies", callback_data="set_cookies_btn")],
            [InlineKeyboardButton("🔙 Back", callback_data="close_settings")]
        ])
        
        await query.message.edit_text(
            f"⚙️ **Settings**\n\nLeech Mode: {status_text}\n\nIn Leech Mode, you can rename the file and set a custom thumbnail before downloading.",
            reply_markup=buttons
        )
    
    elif data == "set_cookies_btn":
        user_data[user_id] = {'state': 'waiting_cookies'}
        await query.message.reply_text(
            "🍪 **Set Cookies**\n\n"
            "Please send your cookies in one of the following formats:\n"
            "1. **Netscape Format** (File)\n"
            "2. **JSON Format** (File/Text)\n"
            "3. **Header String** (Text)\n\n"
            "Send the file or text now."
        )

    elif data == "toggle_leech":
        current = get_user_setting(user_id, 'leech', False)
        set_user_setting(user_id, 'leech', not current)
        
        # Refresh settings menu
        is_leech = not current
        status_text = "✅ ON" if is_leech else "❌ OFF"
        btn_text = "Disable Leech Mode" if is_leech else "Enable Leech Mode"
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_text, callback_data="toggle_leech")],
            [InlineKeyboardButton("🍪 Set Cookies", callback_data="set_cookies_btn")],
            [InlineKeyboardButton("🔙 Back", callback_data="close_settings")]
        ])
        
        await query.message.edit_text(
            f"⚙️ **Settings**\n\nLeech Mode: {status_text}",
            reply_markup=buttons
        )

    elif data == "close_settings":
        await query.message.delete()

    elif data == "mp3_menu":
        # Show MP3 Quality Options
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Fast 128k", callback_data="set_audio_128")],
            [InlineKeyboardButton("Classic 70k", callback_data="set_audio_70"),
             InlineKeyboardButton("Classic 128k", callback_data="set_audio_128")],
            [InlineKeyboardButton("Classic 160k", callback_data="set_audio_160"),
             InlineKeyboardButton("Classic 320k", callback_data="set_audio_320")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_quality")]
        ])
        await query.message.edit_text("🎵 **Select Audio Quality:**", reply_markup=buttons)

    elif data == "back_to_quality":
        # Return to main quality menu
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("1080p", callback_data="set_quality_1080"),
             InlineKeyboardButton("720p", callback_data="set_quality_720")],
            [InlineKeyboardButton("480p", callback_data="set_quality_480"),
             InlineKeyboardButton("360p", callback_data="set_quality_360")],
            [InlineKeyboardButton("🎵 MP3 / Audio", callback_data="mp3_menu")]
        ])
        await query.message.edit_text("📹 **Select Video Quality:**", reply_markup=buttons)
        
    elif data.startswith("set_quality_") or data.startswith("set_audio_"):
        # Quality selected (Video or Audio)
        if data.startswith("set_quality_"):
            quality = data.split("_")[2]
            mode = 'video'
        else:
            quality = data.split("_")[2]
            mode = 'audio'
            # Store special 'audio_128' type string in user_data quality field
            # Actually, let's store "audio_128" in 'quality' and parse it later
            quality = f"audio_{quality}"

        user_data[user_id]['quality'] = quality
        
        url = user_data[user_id].get('url')
        if not url:
            await query.answer("Session expired.", show_alert=True)
            return

        is_leech = get_user_setting(user_id, 'leech', False)
        
        display_quality = quality.replace("audio_", "MP3 ") if "audio" in quality else f"{quality}p"

        if not is_leech:
            await query.message.delete()
            await process_download(client, query.message, user_data[user_id])
            # Cleanup
            if user_id in user_data:
                del user_data[user_id]
        else:
            # Leech Mode: Fetch info and show menu
            await query.message.edit_text("🔎 Fetching info...")
            try:
                loop = asyncio.get_running_loop()
                info = await loop.run_in_executor(None, functools.partial(fetch_info_sync, url))
                title = info.get('title', 'Unknown Title')
                
                user_data[user_id]['title'] = title
                user_data[user_id]['state'] = 'idle'
                
                text = f"📹 **Media Found**\n\n**Title:** `{title}`\n**Quality:** {display_quality}\n\nSelect an action:"
                
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Rename", callback_data="leech_rename"),
                     InlineKeyboardButton("🖼️ Set Thumbnail", callback_data="leech_thumb")],
                    [InlineKeyboardButton("🚀 Upload Now", callback_data="leech_upload")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="leech_cancel")]
                ])
                
                await query.message.edit_text(text, reply_markup=buttons)
            except Exception as e:
                 await query.message.edit_text(f"❌ Error fetching info: {str(e)}")

    elif data == "leech_rename":
        user_data[user_id]['state'] = 'waiting_rename'
        await query.message.reply_text("✏️ Send me the new filename (without extension):")
        
    elif data == "leech_thumb":
        user_data[user_id]['state'] = 'waiting_thumb'
        await query.message.reply_text("🖼️ Send me the new thumbnail (photo):")
        
    elif data == "leech_upload":
        if user_id not in user_data or 'url' not in user_data[user_id]:
            await query.answer("Session expired.", show_alert=True)
            return
        
        await query.message.delete()
        await process_download(client, query.message, user_data[user_id])
        # Cleanup state
        if user_id in user_data:
            del user_data[user_id]
            
    elif data == "leech_cancel":
        if user_id in user_data:
            del user_data[user_id]
        await query.message.delete()
        await query.message.reply_text("❌ Operation cancelled.")

# Registered before generic text_handler to ensure priority
@app.on_message(filters.regex(r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/") & filters.private)
async def youtube_handler(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Extract URL
    regex = r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/[^\s]+"
    match = re.search(regex, message.text)
    if not match:
        return
    url = match.group(0)

    # Store URL and setup state
    user_data[user_id] = {
        'state': 'waiting_quality',
        'url': url,
        'title': None,
        'rename': None,
        'thumb_path': None,
        'original_message_id': message.id,
        'user': message.from_user,
        'quality': '1080' # default fallback
    }
    
    # Ask for Quality
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("1080p", callback_data="set_quality_1080"),
         InlineKeyboardButton("720p", callback_data="set_quality_720")],
        [InlineKeyboardButton("480p", callback_data="set_quality_480"),
         InlineKeyboardButton("360p", callback_data="set_quality_360")],
        [InlineKeyboardButton("🎵 MP3 / Audio", callback_data="mp3_menu")]
    ])
    
    await message.reply_text("📹 **Select Video Quality:**", reply_markup=buttons)

# Generic text handler (runs after specific handlers)
@app.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_data.get(user_id, {}).get('state')

    if state == 'waiting_cookies':
        content = message.text
        if content:
            netscape_content = convert_to_netscape(content)
            with open('cookies.txt', 'w', encoding='utf-8') as f:
                f.write(netscape_content)
            
            await message.reply_text("✅ Cookies saved successfully!")
            if user_id in user_data:
                del user_data[user_id]
        return

    if state == 'waiting_rename':
        new_name = message.text.strip()
        user_data[user_id]['rename'] = new_name
        user_data[user_id]['state'] = 'idle'
        
        await message.reply_text(f"✅ Name set to: `{new_name}`")

@app.on_message(filters.document & filters.private)
async def document_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_data.get(user_id, {}).get('state')

    if state == 'waiting_cookies':
        doc_path = await message.download(file_name=f"downloads/temp_cookies_{user_id}.txt")
        try:
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            netscape_content = convert_to_netscape(content)
            with open('cookies.txt', 'w', encoding='utf-8') as f:
                f.write(netscape_content)
            
            await message.reply_text("✅ Cookies file saved successfully!")
        except Exception as e:
             await message.reply_text(f"❌ Error reading file: {e}")
        finally:
            if os.path.exists(doc_path):
                os.remove(doc_path)
            if user_id in user_data:
                del user_data[user_id]
        return

@app.on_message(filters.photo & filters.private)
async def photo_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in user_data and user_data[user_id].get('state') == 'waiting_thumb':
        msg = await message.reply_text("⬇️ Downloading thumbnail...")
        path = await message.download(file_name=f"downloads/thumbs/{user_id}.jpg")
        
        user_data[user_id]['thumb_path'] = path
        user_data[user_id]['state'] = 'idle'
        
        await msg.edit_text("✅ Thumbnail set.")

async def process_download(client: Client, message: Message, data: dict):
    """
    Handles the actual download and upload process.
    """
    url = data['url']
    custom_name = data.get('rename')
    custom_thumb = data.get('thumb_path')
    original_msg_id = data.get('original_message_id')
    user = data.get('user', message.from_user) # Fallback to message.from_user if not in data
    quality = data.get('quality', '1080')

    mode = 'video'
    target_quality = quality
    if quality.startswith('audio_'):
        mode = 'audio'
        target_quality = quality.split('_')[1]
        display_text = f"MP3 {target_quality}k"
    else:
        display_text = f"{quality}p"

    # Send processing message
    status_msg = await client.send_message(message.chat.id, f"⬇️ Downloading {mode} ({display_text})...")
    
    timestamp = int(time.time())
    
    # Determine Output Template
    if custom_name:
        # Sanitize filename
        safe_name = "".join([c for c in custom_name if c.isalpha() or c.isdigit() or c in " .-_"]).strip()
        output_template = f"downloads/{timestamp}/{safe_name}.%(ext)s"
    else:
        output_template = f"downloads/{timestamp}/%(title)s.%(ext)s"
    
    try:
        loop = asyncio.get_running_loop()
        
        info = await loop.run_in_executor(
            None, 
            functools.partial(download_media_sync, url, output_template, target_quality, writethumbnail=True, mode=mode)
        )
        
        title = info.get('title', 'Unknown Title')
        duration = info.get('duration', 0)
        width = info.get('width', 0)
        height = info.get('height', 0)
        
        files_path = f"downloads/{timestamp}/"
        
        # Determine which thumbnail to use
        # 1. Custom thumb if provided
        # 2. Downloaded thumb from yt-dlp
        thumb_to_use = None
        
        if custom_thumb and os.path.exists(custom_thumb):
            thumb_to_use = custom_thumb
        else:
            thumb_files = glob.glob(f"{files_path}*.jpg") + glob.glob(f"{files_path}*.webp") + glob.glob(f"{files_path}*.png")
            if thumb_files:
                thumb_to_use = thumb_files[0]
        
        # Find the uploaded file
        if mode == 'audio':
             media_files = glob.glob(f"{files_path}*.mp3")
        else:
             media_files = glob.glob(f"{files_path}*.mp4")

        if not media_files:
            await status_msg.edit_text(f"❌ Error: Could not find downloaded {mode} file.")
            return
        
        media_path = media_files[0]
        
        # Construct Caption
        final_title = custom_name if custom_name else title
        mention = user.mention if user else "Unknown"
        caption = f"🎥 **{final_title}**\n**Quality:** {display_text}\n\n👤 **Requested by:** {mention}"
        
        await status_msg.edit_text("⬆️ Uploading to Telegram...")
        
        if mode == 'audio':
            await client.send_audio(
                chat_id=message.chat.id,
                audio=media_path,
                caption=caption,
                duration=duration,
                thumb=thumb_to_use,
                title=final_title,
                performer=info.get('uploader', 'Unknown')
            )
        else:
            await client.send_video(
                chat_id=message.chat.id,
                video=media_path,
                caption=caption,
                duration=duration,
                width=width,
                height=height,
                thumb=thumb_to_use,
                supports_streaming=True
            )
        
        await status_msg.delete()
        
        # Delete the user's original link/message
        if original_msg_id:
             try:
                # Need to use delete_messages to specify message id
                await client.delete_messages(chat_id=message.chat.id, message_ids=original_msg_id)
             except Exception:
                pass

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")
    
    finally:
        # Cleanup download folder
        if os.path.exists(f"downloads/{timestamp}"):
            shutil.rmtree(f"downloads/{timestamp}", ignore_errors=True)
        
        # Clean up custom thumb if used
        if custom_thumb and os.path.exists(custom_thumb):
            try:
                os.remove(custom_thumb)
            except:
                pass

async def web_handler(request):
    return web.Response(text="Bot is running")

async def api_info_handler(request):
    """
    API Endpoint: /api/info?url=...
    Returns JSON metadata for the given YouTube URL.
    """
    url = request.query.get('url')
    if not url:
        return web.json_response({'error': 'Missing url parameter'}, status=400)
    
    try:
        loop = asyncio.get_running_loop()
        # Use fetch_info_sync which reuses our cookies configuration
        info = await loop.run_in_executor(None, functools.partial(fetch_info_sync, url))
        
        # Extract relevant fields
        response_data = {
            'title': info.get('title'),
            'duration': info.get('duration'),
            'thumbnail': info.get('thumbnail'),
            'uploader': info.get('uploader'),
            'view_count': info.get('view_count'),
            'formats': []
        }
        
        # Simplify formats for the API consumer
        for f in info.get('formats', []):
            # Only keep useful formats (e.g., mp4 with audio/video or specific resolutions)
            # This is a raw dump of available streams.
            response_data['formats'].append({
                'format_id': f.get('format_id'),
                'ext': f.get('ext'),
                'resolution': f.get('resolution'),
                'url': f.get('url'), # Note: might be IP locked
                'filesize': f.get('filesize'),
                'vcodec': f.get('vcodec'),
                'acodec': f.get('acodec')
            })
            
        return web.json_response(response_data)
        
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def on_startup(app_runner):
    print("Starting Telegram Bot...")
    await app.start()

async def on_cleanup(app_runner):
    print("Stopping Telegram Bot...")
    await app.stop()

def main():
    print("Starting Web Server...")
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    
    # Create the web application
    web_app = web.Application()
    web_app.router.add_get("/", web_handler)
    web_app.router.add_get("/api/info", api_info_handler)
    
    # Register startup/cleanup hooks
    web_app.on_startup.append(on_startup)
    web_app.on_cleanup.append(on_cleanup)
    
    # Run the web application
    # This handles the main loop
    port = int(os.environ.get("PORT", 8000))
    web.run_app(web_app, port=port)

if __name__ == "__main__":
    main()
