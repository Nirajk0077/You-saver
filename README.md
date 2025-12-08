# Telegram YouTube Downloader Bot

A powerful Telegram bot to download YouTube videos in **1080p** resolution with audio. It includes advanced features like **Leech Mode** (for renaming and custom thumbnails), **Cookie Support** (for age-restricted content), and automatic link deletion.

## 🚀 Features

*   **High Quality**: Downloads videos in 1080p (merged with best audio) by default.
*   **Leech Mode**: Toggleable mode to:
    *   Rename the file before uploading.
    *   Set a custom thumbnail.
*   **Cookie Support**: Upload cookies in **JSON**, **Netscape**, or **Header String** format to bypass restrictions.
*   **Smart Cleanup**: Automatically deletes the user's original link message after a successful upload.
*   **User Mentions**: Mentions the requester in the video caption.
*   **Deployment Ready**: Ready-to-use configurations for Koyeb, Heroku, Render, and Docker/VPS.

## 🛠 Configuration

You need the following environment variables:

*   `API_ID`: Get from [my.telegram.org](https://my.telegram.org).
*   `API_HASH`: Get from [my.telegram.org](https://my.telegram.org).
*   `BOT_TOKEN`: Get from [@BotFather](https://t.me/BotFather).

## 🤖 Commands

*   `/start` - Start the bot and access the **Settings** menu.
*   `/set_cookies` - Upload your cookies (Netscape, JSON, or Header String).

## ☁️ Deployment

### 1. Koyeb / Render / Railway
This repository contains a `Dockerfile`. Simply connect your repository to the service and deploy. ensure you set the **Environment Variables** in the dashboard.

### 2. Heroku
1.  Fork this repository.
2.  Create a new app on Heroku.
3.  Go to **Settings** -> **Config Vars** and add `API_ID`, `API_HASH`, and `BOT_TOKEN`.
4.  Deploy the branch.
5.  Turn on the worker dyno.

### 3. VPS (Docker)
```bash
# Clone the repository
git clone https://github.com/yourusername/your-repo.git
cd your-repo

# Build the image
docker build -t youtube-bot .

# Run the container (replace vars)
docker run -d \
  -e API_ID=123456 \
  -e API_HASH=your_api_hash \
  -e BOT_TOKEN=your_bot_token \
  youtube-bot
```

### 4. Local Run (Python)
Requirements: Python 3.8+, `ffmpeg` installed.

```bash
# Install dependencies
pip install -r requirements.txt

# Create a .env file or export vars
export API_ID=12345
export API_HASH=your_hash
export BOT_TOKEN=your_token

# Run the bot
python bot.py
```

## 🍪 How to Use Cookies
1.  Use the `/set_cookies` command or click "Set Cookies" in Settings.
2.  Send the cookie file or text.
    *   **Extension**: Use 'Get cookies.txt LOCALLY' extension for Chrome/Firefox to export Netscape format.
    *   **Header**: Or just copy the `Cookie:` header string from your browser's network tab.
3.  The bot will convert and use them automatically.
