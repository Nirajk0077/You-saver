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
from auth_helper import AuthSession
from progress import progress_for_pyrogram, humanbytes

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
# active_logins = { user_id: AuthSession }
active_logins = {}
# cancel_processes = { message_id: bool }
cancel_processes = {}

def save_cookies_globally(user_id, content):
    """Saves cookies to user-specific file and global cookies.txt"""
    if not os.path.exists("cookies"):
        os.makedirs("cookies")

    # Save to user specific file
    user_path = f"cookies/cookies_{user_id}.txt"
    with open(user_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # Save to global file
    with open("cookies.txt", 'w', encoding='utf-8') as f:
        f.write(content)

    return user_path

def get_user_setting(user_id, key, default):
    if user_id not in user_settings:
        user_settings[user_id] = {}
    return user_settings[user_id].get(key, default)

def set_user_setting(user_id, key, value):
    if user_id not in user_settings:
        user_settings[user_id] = {}
    user_settings[user_id][key] = value

class DownloadProgressHook:
    def __init__(self, start_time=None, loop=None, status_msg=None, check_cancel=None):
        self.start_time = start_time
        self.loop = loop
        self.status_msg = status_msg
        self.check_cancel = check_cancel
        self.last_update = 0

    def __call__(self, d):
        if self.check_cancel and self.check_cancel():
            raise Exception("Cancelled by user")

        if d['status'] == 'finished':
            print('Download finished, now converting ...')

        if d['status'] == 'downloading' and self.status_msg:
            now = time.time()
            if now - self.last_update > 5:
                self.last_update = now
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                current = d.get('downloaded_bytes', 0)

                if total > 0:
                    asyncio.run_coroutine_threadsafe(
                        progress_for_pyrogram(
                            current,
                            total,
                            "⬇️ Downloading...",
                            self.status_msg,
                            self.start_time,
                            self.check_cancel,
                            force=True
                        ),
                        self.loop
                    )

def download_video_sync(url, output_path, quality, writethumbnail=True, cookiefile=None, progress_args=None):
    """
    Synchronous wrapper for yt-dlp download to be run in an executor.
    Quality should be '1080', '720', '480', '360' or 'mp3_...'.
    """
    hook = DownloadProgressHook(*progress_args) if progress_args else DownloadProgressHook()

    ydl_opts = {
        'outtmpl': output_path,
        'writethumbnail': writethumbnail,
        'quiet': True,
        'progress_hooks': [hook],
        'noplaylist': True,
    }

    if 'mp3' in quality:
        # Audio Mode
        if 'fast' in quality:
            # Fast 128k - best audio, no force re-encode unless needed, prefer 128k range
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }]
        else:
            # Classic MP3 - Force re-encode to specific bitrate
            # set_quality_mp3_70 -> 70
            bitrate = quality.split('_')[-1]
            if not bitrate.isdigit():
                bitrate = '128'

            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate,
            }]
    else:
        # Video Mode
        # Default to 1080 if invalid
        if quality not in ['1080', '720', '480', '360']:
            quality = '1080'

        format_str = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'
        ydl_opts['format'] = format_str
        ydl_opts['merge_output_format'] = 'mp4'

    if cookiefile and os.path.exists(cookiefile):
        ydl_opts['cookiefile'] = cookiefile
    elif os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
    
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return info

def fetch_info_sync(url, cookiefile=None):
    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
    }

    if cookiefile and os.path.exists(cookiefile):
        ydl_opts['cookiefile'] = cookiefile
    elif os.path.exists('cookies.txt'):
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
        "Send me a YouTube link to download video.\n\n"
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
        auto_thumb = get_user_setting(user_id, 'auto_thumb', True)

        leech_status = "✅ ON" if is_leech else "❌ OFF"
        leech_btn_text = "Disable Leech Mode" if is_leech else "Enable Leech Mode"

        thumb_status = "✅ ON" if auto_thumb else "❌ OFF"
        thumb_btn_text = "Disable Auto Thumbnail" if auto_thumb else "Enable Auto Thumbnail"
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(leech_btn_text, callback_data="toggle_leech")],
            [InlineKeyboardButton(thumb_btn_text, callback_data="toggle_thumb")],
            [InlineKeyboardButton("🍪 Set Cookies", callback_data="set_cookies_btn")],
            [InlineKeyboardButton("🔙 Back", callback_data="close_settings")]
        ])
        
        await query.message.edit_text(
            f"⚙️ **Settings**\n\nLeech Mode: {leech_status}\nAuto Thumbnail: {thumb_status}\n\nIn Leech Mode, you can rename the file and set a custom thumbnail before downloading.",
            reply_markup=buttons
        )
    
    elif data == "set_cookies_btn":
        # user_data[user_id] = {'state': 'waiting_cookies'}

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Login to YouTube (Auto)", callback_data="login_youtube")],
            [InlineKeyboardButton("📤 Upload Cookies File", callback_data="upload_cookies_file")],
            [InlineKeyboardButton("🔙 Back", callback_data="settings")]
        ])

        await query.message.edit_text(
            "🍪 **Set Cookies**\n\n"
            "Choose a method to set cookies:\n"
            "1. **Login to YouTube**: The bot will log in and generate cookies for you.\n"
            "2. **Upload File**: Manually upload Netscape/JSON cookie file.",
            reply_markup=buttons
        )

    elif data == "upload_cookies_file":
        user_data[user_id] = {'state': 'waiting_cookies'}
        await query.message.reply_text(
            "📤 **Upload Cookies**\n\n"
            "Please send your cookies file (Netscape or JSON format) or paste the content as text."
        )

    elif data == "login_youtube":
        if user_id in active_logins:
            await query.answer("Login session already active.", show_alert=True)
            return

        msg = await query.message.reply_text("🔄 **Initializing Login Session...**\nPlease wait, launching browser...")

        session = AuthSession(user_id)
        active_logins[user_id] = session

        success, message = await session.start()

        if success:
            user_data[user_id] = {'state': 'waiting_email'}
            await msg.edit_text(f"✅ **Browser Launched**\n\n{message}\n\nSend your **Email** now.")
        else:
            del active_logins[user_id]
            await msg.edit_text(f"❌ **Error:** {message}")

    elif data == "toggle_leech":
        current = get_user_setting(user_id, 'leech', False)
        set_user_setting(user_id, 'leech', not current)
        
        # Refresh settings menu
        is_leech = not current
        auto_thumb = get_user_setting(user_id, 'auto_thumb', True)

        leech_status = "✅ ON" if is_leech else "❌ OFF"
        leech_btn_text = "Disable Leech Mode" if is_leech else "Enable Leech Mode"

        thumb_status = "✅ ON" if auto_thumb else "❌ OFF"
        thumb_btn_text = "Disable Auto Thumbnail" if auto_thumb else "Enable Auto Thumbnail"
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(leech_btn_text, callback_data="toggle_leech")],
            [InlineKeyboardButton(thumb_btn_text, callback_data="toggle_thumb")],
            [InlineKeyboardButton("🍪 Set Cookies", callback_data="set_cookies_btn")],
            [InlineKeyboardButton("🔙 Back", callback_data="close_settings")]
        ])
        
        await query.message.edit_text(
            f"⚙️ **Settings**\n\nLeech Mode: {leech_status}\nAuto Thumbnail: {thumb_status}",
            reply_markup=buttons
        )

    elif data == "toggle_thumb":
        current = get_user_setting(user_id, 'auto_thumb', True)
        set_user_setting(user_id, 'auto_thumb', not current)

        # Refresh settings menu
        is_leech = get_user_setting(user_id, 'leech', False)
        auto_thumb = not current

        leech_status = "✅ ON" if is_leech else "❌ OFF"
        leech_btn_text = "Disable Leech Mode" if is_leech else "Enable Leech Mode"

        thumb_status = "✅ ON" if auto_thumb else "❌ OFF"
        thumb_btn_text = "Disable Auto Thumbnail" if auto_thumb else "Enable Auto Thumbnail"

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(leech_btn_text, callback_data="toggle_leech")],
            [InlineKeyboardButton(thumb_btn_text, callback_data="toggle_thumb")],
            [InlineKeyboardButton("🍪 Set Cookies", callback_data="set_cookies_btn")],
            [InlineKeyboardButton("🔙 Back", callback_data="close_settings")]
        ])

        await query.message.edit_text(
            f"⚙️ **Settings**\n\nLeech Mode: {leech_status}\nAuto Thumbnail: {thumb_status}",
            reply_markup=buttons
        )

    elif data == "close_settings":
        await query.message.delete()

    elif data == "refresh_status":
        await query.answer("🔄 Process is running...", show_alert=False)

    elif data.startswith("cancel_dl_"):
        try:
            # data format: cancel_dl_{chat_id}_{message_id}
            parts = data.split("_")
            chat_id = int(parts[-2])
            msg_id = int(parts[-1])
            cancel_key = f"{chat_id}_{msg_id}"

            if cancel_key in cancel_processes:
                cancel_processes[cancel_key] = True
                await query.answer("Cancelling...", show_alert=True)
                await query.message.edit_text("❌ Cancelling operation...")
            else:
                await query.answer("Process not active or already cancelled.", show_alert=True)
        except:
             await query.answer("Error processing cancellation.", show_alert=True)
        
    elif data == "show_mp3_options":
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Fast 128k", callback_data="set_quality_mp3_fast_128")],
            [InlineKeyboardButton("Classic MP3 70k", callback_data="set_quality_mp3_70")],
            [InlineKeyboardButton("Classic MP3 128k", callback_data="set_quality_mp3_128")],
            [InlineKeyboardButton("Classic MP3 160k", callback_data="set_quality_mp3_160")],
            [InlineKeyboardButton("Classic MP3 320k", callback_data="set_quality_mp3_320")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_quality")]
        ])
        await query.message.edit_text("🎵 **Select MP3 Quality:**", reply_markup=buttons)

    elif data == "back_to_quality":
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("1080p", callback_data="set_quality_1080"),
             InlineKeyboardButton("720p", callback_data="set_quality_720")],
            [InlineKeyboardButton("480p", callback_data="set_quality_480"),
             InlineKeyboardButton("360p", callback_data="set_quality_360")],
            [InlineKeyboardButton("🎵 MP3", callback_data="show_mp3_options")]
        ])
        await query.message.edit_text("📹 **Select Quality:**", reply_markup=buttons)

    elif data.startswith("set_quality_"):
        # Quality selected, proceed
        parts = data.split("_")
        if len(parts) > 3: # set_quality_mp3_...
            # e.g. set_quality_mp3_fast_128 -> mp3_fast_128
            # e.g. set_quality_mp3_320 -> mp3_320
            quality = "_".join(parts[2:])
        else:
            quality = parts[2]

        user_data[user_id]['quality'] = quality
        
        url = user_data[user_id].get('url')
        if not url:
            await query.answer("Session expired.", show_alert=True)
            return

        is_leech = get_user_setting(user_id, 'leech', False)
        
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
                # Determine cookie file
                cookiefile = f"cookies/cookies_{user_id}.txt"
                if not os.path.exists(cookiefile):
                    cookiefile = None

                info = await loop.run_in_executor(None, functools.partial(fetch_info_sync, url, cookiefile))
                title = info.get('title', 'Unknown Title')
                
                user_data[user_id]['title'] = title
                user_data[user_id]['state'] = 'idle'
                
                display_quality = quality.replace("mp3_", "MP3 ").replace("_", " ") if "mp3" in quality else f"{quality}p"

                text = f"📹 **Content Found**\n\n**Title:** `{title}`\n**Quality:** {display_quality}\n\nSelect an action:"
                
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
@app.on_message(filters.regex(r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/"))
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
        [InlineKeyboardButton("🎵 MP3", callback_data="show_mp3_options")]
    ])
    
    await message.reply_text("📹 **Select Quality:**", reply_markup=buttons)

# Generic text handler (runs after specific handlers)
@app.on_message(filters.text)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_data.get(user_id, {}).get('state')

    if state == 'waiting_cookies':
        content = message.text
        if content:
            netscape_content = convert_to_netscape(content)
            cookie_path = save_cookies_globally(user_id, netscape_content)
            
            await message.reply_text(f"✅ Cookies saved successfully to `{cookie_path}` and shared globally!")
            if user_id in user_data:
                del user_data[user_id]
        return

    # Login Flow States
    if user_id in active_logins:
        session = active_logins[user_id]
        text_input = message.text.strip()

        if state == 'waiting_email':
            processing_msg = await message.reply_text("🔄 Processing Email...")
            success, msg = await session.enter_email(text_input)

            if success:
                if "password" in msg.lower():
                    user_data[user_id]['state'] = 'waiting_password'
                    await processing_msg.edit_text(f"✅ {msg}")
                else:
                    await processing_msg.edit_text(f"⚠️ {msg}")
            else:
                await processing_msg.edit_text(f"❌ {msg}\n\nTry again or /cancel.")

        elif state == 'waiting_password':
            # Delete password message for security if possible, but telegram bots can't delete user messages easily in private
            processing_msg = await message.reply_text("🔄 Processing Password...")
            success, msg, next_step = await session.enter_password(text_input)

            if success:
                if next_step == "done":
                    # Extract Cookies
                    cookies = await session.get_cookies_netscape()
                    cookie_path = save_cookies_globally(user_id, cookies)

                    await session.close()
                    del active_logins[user_id]
                    if user_id in user_data:
                        del user_data[user_id]

                    await processing_msg.edit_text(f"✅ **Login Successful!**\n\nCookies have been generated, saved to `{cookie_path}`, and shared globally.")
                elif next_step == "otp":
                    user_data[user_id]['state'] = 'waiting_otp'
                    await processing_msg.edit_text(f"🛡️ **2FA Required**\n\n{msg}\n\nEnter the code now.")
                else:
                    await processing_msg.edit_text(f"⚠️ {msg}")
            else:
                 await processing_msg.edit_text(f"❌ {msg}\n\nTry again or /cancel.")

        elif state == 'waiting_otp':
            processing_msg = await message.reply_text("🔄 Verifying OTP...")
            success, msg = await session.enter_otp(text_input)

            if success and "Logged in" in msg:
                 # Extract Cookies
                cookies = await session.get_cookies_netscape()
                cookie_path = save_cookies_globally(user_id, cookies)

                await session.close()
                del active_logins[user_id]
                if user_id in user_data:
                    del user_data[user_id]

                await processing_msg.edit_text(f"✅ **Login Successful!**\n\nCookies have been generated, saved to `{cookie_path}`, and shared globally.")
            else:
                await processing_msg.edit_text(f"ℹ️ {msg}")

        return

    if state == 'waiting_rename':
        new_name = message.text.strip()
        user_data[user_id]['rename'] = new_name
        user_data[user_id]['state'] = 'idle'
        
        await message.reply_text(f"✅ Name set to: `{new_name}`")

@app.on_message(filters.document)
async def document_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_data.get(user_id, {}).get('state')

    if state == 'waiting_cookies':
        doc_path = await message.download(file_name=f"downloads/temp_cookies_{user_id}.txt")
        try:
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            netscape_content = convert_to_netscape(content)
            cookie_path = save_cookies_globally(user_id, netscape_content)
            
            await message.reply_text(f"✅ Cookies file saved successfully to `{cookie_path}` and shared globally!")
        except Exception as e:
             await message.reply_text(f"❌ Error reading file: {e}")
        finally:
            if os.path.exists(doc_path):
                os.remove(doc_path)
            if user_id in user_data:
                del user_data[user_id]
        return

@app.on_message(filters.photo)
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
    user_id = message.chat.id

    # Send processing message
    status_msg = await client.send_message(message.chat.id, f"⬇️ Downloading video ({quality}p)...")
    
    # Initialize cancellation
    cancel_key = f"{message.chat.id}_{status_msg.id}"
    cancel_processes[cancel_key] = False

    def check_cancel():
        return cancel_processes.get(cancel_key, False)

    timestamp = int(time.time())
    
    # Determine Output Template
    if custom_name:
        # Sanitize filename
        safe_name = "".join([c for c in custom_name if c.isalpha() or c.isdigit() or c in " .-_"]).strip()
        output_template = f"downloads/{timestamp}/{safe_name}.%(ext)s"
    else:
        output_template = f"downloads/{timestamp}/%(title)s.%(ext)s"
    
    # Determine cookie file
    cookiefile = f"cookies/cookies_{user_id}.txt"
    if not os.path.exists(cookiefile):
        cookiefile = None

    # Get auto_thumb setting
    auto_thumb = get_user_setting(user_id, 'auto_thumb', True)

    try:
        loop = asyncio.get_running_loop()
        # If custom thumb is provided, we might not need yt-dlp to write one, 
        # but it's safer to let it write one as backup if we don't use it.
        # However, if we have a custom thumb, we will pass it explicitly to send_video.
        
        download_start = time.time()
        info = await loop.run_in_executor(
            None, 
            functools.partial(download_video_sync, url, output_template, quality, writethumbnail=auto_thumb, cookiefile=cookiefile, progress_args=(download_start, loop, status_msg, check_cancel))
        )
        
        title = info.get('title', 'Unknown Title')
        duration = info.get('duration', 0)
        width = info.get('width', 0)
        height = info.get('height', 0)
        
        files_path = f"downloads/{timestamp}/"
        
        # Determine which thumbnail to use
        # 1. Custom thumb if provided
        # 2. Downloaded thumb from yt-dlp (if auto_thumb is True)
        thumb_to_use = None
        
        if custom_thumb and os.path.exists(custom_thumb):
            thumb_to_use = custom_thumb
        elif auto_thumb:
            thumb_files = glob.glob(f"{files_path}*.jpg") + glob.glob(f"{files_path}*.webp") + glob.glob(f"{files_path}*.png")
            if thumb_files:
                thumb_to_use = thumb_files[0]

        # Check for Video or Audio
        video_files = glob.glob(f"{files_path}*.mp4")
        audio_files = glob.glob(f"{files_path}*.mp3")
        
        # Construct Caption
        final_title = custom_name if custom_name else title
        # Use user.mention for a proper clickable link
        mention = user.mention if user else "Unknown"
        
        if video_files:
            video_path = video_files[0]
            # Get languages if available, else default to 'English/Unknown'
            # yt-dlp info might have 'language' or 'requested_subtitles' etc but often it is hard to determine precisely for video file if not in info.
            # However, info dict usually has 'language' field if available.
            languages = info.get('language') or "English"
            file_size = os.path.getsize(video_path)

            caption = (
                f"<b>{final_title}</b>\n\n"
                f"🔊 {languages}\n"
                f"💿 <b>Size:</b> {humanbytes(file_size)}\n"
                f"👤 <b>Requested by:</b> {mention}"
            )

            # Start timer for progress
            start_time = time.time()
            await status_msg.edit_text("⬆️ Uploading Video to Telegram...")

            await client.send_video(
                chat_id=message.chat.id,
                video=video_path,
                caption=caption,
                duration=duration,
                width=width,
                height=height,
                thumb=thumb_to_use,
                supports_streaming=True,
                progress=progress_for_pyrogram,
                progress_args=("⬆️ Uploading Video...", status_msg, start_time, check_cancel)
            )

        elif audio_files:
            audio_path = audio_files[0]
            languages = info.get('language') or "English"
            file_size = os.path.getsize(audio_path)

            display_quality = quality.replace("mp3_", "MP3 ").replace("_", " ")
            caption = (
                f"<b>{final_title}</b>\n\n"
                f"🔊 {languages}\n"
                f"💿 <b>Size:</b> {humanbytes(file_size)}\n"
                f"👤 <b>Requested by:</b> {mention}"
            )

            start_time = time.time()
            await status_msg.edit_text("⬆️ Uploading Audio to Telegram...")

            await client.send_audio(
                chat_id=message.chat.id,
                audio=audio_path,
                caption=caption,
                duration=duration,
                performer=info.get('uploader'),
                title=final_title,
                thumb=thumb_to_use,
                progress=progress_for_pyrogram,
                progress_args=("⬆️ Uploading Audio...", status_msg, start_time, check_cancel)
            )

        else:
            await status_msg.edit_text("❌ Error: Could not find downloaded file.")
            return
        
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
        # Cleanup cancellation key
        if 'cancel_key' in locals() and cancel_key in cancel_processes:
            del cancel_processes[cancel_key]

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

async def cleanup_sessions_task():
    """
    Periodically checks for and cleans up inactive login sessions.
    """
    while True:
        try:
            current_time = time.time()
            to_remove = []

            for user_id, session in list(active_logins.items()):
                # If session is inactive for more than 5 minutes, close it
                if current_time - session.last_activity > 300: # 300 seconds = 5 minutes
                    try:
                        await session.close()
                    except:
                        pass
                    to_remove.append(user_id)

            for user_id in to_remove:
                if user_id in active_logins:
                    del active_logins[user_id]
                # Also clean up user_data state if stuck in login flow
                if user_id in user_data and user_data[user_id].get('state') in ['waiting_email', 'waiting_password', 'waiting_otp']:
                    del user_data[user_id]

        except Exception as e:
            print(f"Error in cleanup task: {e}")

        await asyncio.sleep(60) # Run every minute

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", web_handler)
    server.router.add_get("/api/info", api_info_handler)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")

async def main():
    print("Bot is starting...")
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    if not os.path.exists("cookies"):
        os.makedirs("cookies")
    
    # Start bot and web server
    await app.start()
    await start_web_server()

    # Start background cleanup task
    asyncio.create_task(cleanup_sessions_task())

    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
