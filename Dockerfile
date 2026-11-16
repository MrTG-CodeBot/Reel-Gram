FROM python:3.10-slim

# Install system dependencies (ffmpeg is required by yt-dlp, nodejs provides JS runtime for n-sig solving)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
