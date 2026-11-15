<p align="center">
  <img src="assets/logo.jpg" alt="ʀᴇᴇʟɢʀᴀᴍ Logo" width="180" style="border-radius: 24px;" />
</p>

<h1 align="center">🎬 ʀᴇᴇʟɢʀᴀᴍ</h1>

<p align="center">
  <b>High-speed, multi-user Instagram Reels, Posts, Stories & Highlights to Telegram automation service.</b>
</p>

<p align="center">
  <a href="https://github.com/MrTG-CodeBot/Reel-Gram/stargazers"><img src="https://img.shields.io/github/stars/MrTG-CodeBot/Reel-Gram?style=for-the-badge&logo=github&color=gold" alt="Stars" /></a>
  <a href="https://github.com/MrTG-CodeBot/Reel-Gram/network/members"><img src="https://img.shields.io/github/forks/MrTG-CodeBot/Reel-Gram?style=for-the-badge&logo=github&color=blue" alt="Forks" /></a>
  <img src="https://img.shields.io/badge/Language-Python%203.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Language: Python 3.10+" />
  <img src="https://img.shields.io/badge/Framework-python--telegram--bot%20v20+-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Framework: python-telegram-bot" />
  <img src="https://img.shields.io/badge/Database-MongoDB%20Atlas-47A248?style=for-the-badge&logo=mongodb&logoColor=white" alt="Database: MongoDB" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Engine-yt--dlp%20%2B%20FFmpeg-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="Engine: yt-dlp" />
  <img src="https://img.shields.io/badge/API-Instagrapi-E4405F?style=for-the-badge&logo=instagram&logoColor=white" alt="API: Instagrapi" />
  <a href="https://github.com/MrTG-CodeBot/Reel-Gram/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue?style=for-the-badge" alt="License: MIT" /></a>
</p>

---

ʀᴇᴇʟɢʀᴀᴍ is a production-grade, self-hosted automation service that monitors Instagram DMs for shared **Reels, Posts, Carousels, Stories, and Highlights**, downloads them at original quality, and forwards them directly to your Telegram chat in real time.

Features multi-user account linking, automated Instagram force-follow checks, direct CDN streaming, album batching, clean button navigation, interactive owner analytics, and automated crash recovery.

---

## ⚡ Key Features

- **Full Instagram Media Support** — Automatically detects and downloads:
  - 🎬 **Reels** — Full resolution MP4 video with synced audio.
  - 📸 **Posts** — Single photos and high-bitrate videos.
  - 📚 **Carousels & Albums** — Delivered as native Telegram media groups in batches of 10.
  - ⏱️ **Stories** — Active 24-hour stories downloaded via direct CDN or username lookup.
  - 🌟 **Highlights** — Full highlights or specific highlight items (including `/s/` shortlinks).
- **Clean Media Delivery** — Media is delivered without cluttering captions, featuring interactive inline buttons for sender attribution and source links (`[ 👤 Sent by: @user ]` and `[ 🔗 Link ]`).
- **Dual Instagram Account Linking** — Connect up to **2 Instagram accounts** per Telegram chat (e.g. personal & creator) with exclusive ownership protection.
- **Fast-Mode Account Linking** — Generates secure `RG-XXXXXX` verification codes. When registration begins, polling accelerates to **4 seconds** for sub-3-second verification.
- **Dual Force-Subscribe Verification**:
  - **Telegram**: Require users to join a specific channel/group before accessing bot features.
  - **Instagram**: Require users to follow the bot account ([@reelgram_sync](https://www.instagram.com/reelgram_sync/)) to receive media.
- **Direct CDN Streaming & Fallbacks** — Extracts direct video/image CDN streams from DM payloads for instant downloads, backed by `yt-dlp` and `instagrapi` engines.
- **Owner Analytics & Control** — Interactive `/stats` dashboard, `/users` viewer, real-time new user alerts, and mass broadcast messaging.
- **Crash Recovery & Deduplication** — MongoDB tracks message IDs and media URLs. Pending tasks are re-queued automatically upon service restart.
- **Deployment Ready** — Includes `Dockerfile`, `railway.json`, and `render.yaml` with built-in health check server for 24/7 cloud hosting.

---

## 🔄 How It Works

```mermaid
flowchart TD
    subgraph Telegram ["📱 Telegram Interface"]
        TG_User["User sends /register &lt;username&gt;"]
        TG_Code["Bot generates verification code: RG-XXXXXX"]
        TG_Success["Telegram delivers confirmed link alert"]
        TG_Media["Telegram delivers Reel / Post / Story / Highlight"]
    end

    subgraph Instagram ["📸 Instagram Direct"]
        IG_Follow["User follows @reelgram_sync"]
        IG_DM["User DMs RG-XXXXXX"]
        IG_Reply["Instagram sends: ✅ Account Verified!"]
        IG_SendMedia["User shares Reel, Post, Story, or Highlight"]
    end

    subgraph Backend ["⚙️ ʀᴇᴇʟɢʀᴀᴍ Engine"]
        FastPoll["Fast Mode Polling (4s)"]
        FollowCheck["Relationship Check (user_friendship_v1)"]
        DBSync["MongoDB stores user link & chat_id"]
        WorkerQueue["Thread-safe Task Queue"]
        Downloader["yt-dlp + instagrapi CDN Streaming"]
        Uploader["Telegram Bot API (send_video / send_photo / send_media_group)"]
    end

    TG_User --> TG_Code
    TG_Code --> FastPoll
    TG_Code -.-> IG_Follow
    IG_Follow --> IG_DM
    IG_DM --> FollowCheck
    FollowCheck --> DBSync
    DBSync --> IG_Reply
    DBSync --> TG_Success
    IG_SendMedia --> WorkerQueue
    WorkerQueue --> Downloader
    Downloader --> Uploader
    Uploader --> TG_Media
```

---

## 📋 Prerequisites

- **Python**: Version 3.10 or higher
- **FFmpeg**: Bundled automatically via `imageio-ffmpeg` or installed via system package manager
- **MongoDB**: A free cloud database cluster from [MongoDB Atlas](https://www.mongodb.com/atlas) or a local MongoDB instance
- **Telegram Bot Token**: Created via [@BotFather](https://t.me/BotFather)
- **Instagram Account**: Dedicated bot account (e.g. [@reelgram_sync](https://www.instagram.com/reelgram_sync/))

---

## 🚀 Setup & Installation

### 1. Clone the Repository

```bash
git clone https://github.com/MrTG-CodeBot/Reel-Gram.git
cd Reel-Gram
```

### 2. Set Up Virtual Environment

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install FFmpeg (Optional on systems with imageio-ffmpeg)

- **Ubuntu / Debian**:
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```
- **macOS** (Homebrew):
  ```bash
  brew install ffmpeg
  ```
- **Windows**:
  ```powershell
  winget install Gyan.FFmpeg
  ```

---

## ⚙️ Configuration (.env)

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Configure your environment variables:

| Variable | Description | Required | Example |
|---|---|:---:|---|
| `INSTAGRAM_USERNAME` | Instagram handle of your bot account | **Yes** | `reelgram_sync` |
| `INSTAGRAM_PASSWORD` | Password for your Instagram bot account | **Yes** | `YourSecurePassword123` |
| `INSTAGRAM_SESSION_ID` | Session ID cookie (optional fallback) | No | `64603757963%3A...` |
| `TELEGRAM_BOT_TOKEN` | Token obtained from [@BotFather](https://t.me/BotFather) | **Yes** | `123456789:ABCdefGHIjkl...` |
| `TELEGRAM_CHAT_ID` | Fallback chat ID for unlinked media | No | `1342641151` |
| `MONGODB_URI` | MongoDB connection URI | **Yes** | `mongodb+srv://user:pass@cluster0...` |
| `MONGODB_DB_NAME` | Database name | No | `reelgram` |
| `OWNER_ID` | Your Telegram user ID (for admin commands) | **Yes** | `1342641151` |
| `LOG_CHANNEL_ID` | Channel ID to log new user registrations | No | `-1001234567890` |
| `DEVELOPER_USERNAME` | Developer handle shown in `/developer` | No | `MrTG_Coder` |
| `FORCE_SUB_INSTAGRAM` | Require users to follow the bot on Instagram | No | `true` |
| `FORCE_SUB_CHANNEL_ID` | Telegram channel ID for forced Telegram join | No | `-1001234567890` |
| `FORCE_SUB_INVITE_LINK` | Invite link for forced Telegram join | No | `https://t.me/your_channel` |
| `DOWNLOAD_PATH` | Path for temporary files | No | `downloads/` |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) | No | `INFO` |

---

## 🏃 Running the Service

Start the application:

```bash
python main.py
```

The system will initialize:
1. `HealthCheckServer` — Lightweight HTTP server on `$PORT` for cloud web service compatibility.
2. `InstagramMonitorThread` — Inbox monitor polling for incoming DMs and message requests.
3. `DownloadWorker` pool — Concurrently downloads and delivers media to Telegram.
4. `TelegramRegistrationBot` — Handles commands, account linking, and admin tools.

---

## 📖 Commands & Usage

### 📱 User Commands

| Command | Description |
|---|---|
| `/start` | Open the interactive main menu |
| `/register <username>` | Generate a verification code to link an Instagram account |
| `/status` | View your linked Instagram accounts and status |
| `/unlink` | Unlink your Instagram account(s) from Telegram |
| `/help` | View the step-by-step user guide |
| `/developer` | View developer contact details |

### 👑 Admin Commands (Owner Only)

| Command | Description |
|---|---|
| `/stats` | Interactive dashboard showing user metrics, media counts, and DB storage |
| `/users` | Inspect the latest registered users and delivery statistics |
| `/broadcast` | Send announcements to all registered bot users |

---

## 🐳 Docker Deployment

A production-ready `Dockerfile` is included:

```bash
# Build image
docker build -t reelgram .

# Run container
docker run -d \
  --name reelgram \
  --restart always \
  --env-file .env \
  reelgram
```

---

## ☁️ Cloud Hosting

### Railway
1. Push your repository to GitHub.
2. Create a **New Project** in [Railway](https://railway.app) from your GitHub repo.
3. Add the environment variables from `.env.example` in Railway's dashboard.
4. Railway builds the `Dockerfile` automatically and manages process restarts via `railway.json`.

### Render
1. In the [Render Dashboard](https://dashboard.render.com), click **New +** → **Background Worker** (or **Web Service** using the built-in HTTP health check).
2. Connect your repository.
3. Set Build Command to `pip install -r requirements.txt` and Start Command to `python main.py`.
4. Supply your environment variables and deploy.

---

## 📂 Project Structure

```
Reel-Gram/
├── main.py                  # Service entrypoint, worker pools & lifecycle management
├── config.py                # Environment configuration & logging setup
├── requirements.txt         # Project dependencies
├── Dockerfile               # Container build configuration
├── railway.json             # Railway hosting settings
├── render.yaml              # Render blueprint settings
├── .env.example             # Environment variable template
│
├── instagram/
│   ├── login.py             # Instagrapi authentication & session persistence
│   ├── monitor.py           # Inbox polling & auto-approval of message requests
│   ├── handler.py           # Message routing, follow verification & DM replies
│   ├── extractor.py         # Payload parser for Reels, Posts, Stories & Highlights
│   └── parser.py            # Shortcode and primary key utilities
│
├── downloader/
│   ├── download.py          # Unified media downloader (yt-dlp, instagrapi, direct CDN)
│   ├── validator.py         # URL regex validation & shortlink decoding
│   └── cleaner.py           # Temporary file cleanup
│
├── telegram_bot/
│   ├── bot.py               # Telegram bot client factory
│   ├── registration_bot.py  # User commands, verification flows, admin stats & broadcast
│   ├── sender.py            # Thread-safe synchronous upload wrapper
│   └── uploader.py          # Media uploader (videos, photos, and batched albums)
│
├── database/
│   ├── db.py                # MongoDB connection provider
│   └── models.py            # Database schemas, tracking, and metric aggregations
│
├── assets/                  # Brand assets & logos
├── downloads/               # Temporary file storage (auto-cleaned)
└── logs/                    # Application runtime logs
```

---

## 👨‍💻 Author & Credits

Developed by **Amal Nath**

- **Telegram**: [@MrTG_Coder](https://t.me/MrTG_Coder)
- **Instagram**: [@amal_.nath_](https://www.instagram.com/amal_.nath_/)
- **Bot Instagram**: [@reelgram_sync](https://www.instagram.com/reelgram_sync/)

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
