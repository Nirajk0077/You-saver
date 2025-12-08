FROM python:3.10-slim

# Install system dependencies (ffmpeg is critical for merging streams)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and dependencies
RUN playwright install --with-deps chromium

# Copy the rest of the application
COPY . .

# Expose the port for the web server
EXPOSE 8000

# Run the bot
CMD ["python", "bot.py"]
