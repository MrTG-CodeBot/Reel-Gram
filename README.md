# 🎬 ʀᴇᴇʟɢʀᴀᴍ

> **High-speed, multi-user Instagram Reels to Telegram automation bot.**

ʀᴇᴇʟɢʀᴀᴍ is a production-ready, self-hosted automation service that monitors Instagram DMs for shared Reels, downloads them at maximum available quality via `yt-dlp` and `ffmpeg`, and delivers them straight to your Telegram chat in real time.

Supports multi-user account linking, automated Instagram force-follow verification, instant DM confirmations, real-time owner metrics, and automated crash recovery.

---

## ⚡ Key Highlights

- **Instant Reel Delivery** — Polls Instagram Direct inbox and automatically handles incoming messages, shared clips, and pending message requests.
- **Max-Quality Downloads** — Leverages `yt-dlp` and `ffmpeg` to download the highest quality MP4 video stream available.
- **Fast-Mode Account Linking** — Generates secure `verify RG-XXXXXX` codes. When a link starts, polling drops down to **4 seconds** for sub-3-second verification.
- **Instagram Direct DM Feedback** — Users receive confirmation and status messages directly inside their Instagram DM thread.
- **Dual Force-Subscribe Support**:
  - **Telegram**: Require users to join a specific channel/group before accessing bot features.
  - **Instagram**: Require users to follow the bot account ([@reelgram_sync](https://www.instagram.com/reelgram_sync/)) to link accounts or receive Reels.
- **Owner Analytics & Control** — Interactive `/stats` dashboard, `/users` viewer, real-time new user alerts, and broadcast messaging.
- **Crash Recovery & Deduplication** — MongoDB tracks message IDs and video URLs. Incomplete downloads are resumed upon bot restart.
- **Deployment Ready** — Includes `Dockerfile` and `railway.json` for one-click persistent hosting on Railway, Docker, or VPS.

---

## 🔄 How It Works

```mermaid
flowchart TD
    subgraph Telegram ["📱 Telegram Interface"]
        TG_User["User sends /register &lt;username&gt;"]
        TG_Code["Bot generates verification code: verify RG-XXXXXX"]
        TG_Success["Telegram delivers confirmed link alert"]
        TG_Reel["Telegram delivers downloaded Reel video"]
    end

    subgraph Instagram ["📸 Instagram Direct"]
        IG_Follow["User follows @reelgram_sync"]
        IG_DM["User DMs verify RG-XXXXXX"]
        IG_Reply["Instagram sends: ✅ Account Verified!"]
        IG_SendReel["User shares Reel to @reelgram_sync"]
    end

    subgraph Backend ["⚙️ ʀᴇᴇʟɢʀᴀᴍ Engine"]
        FastPoll["Fast Mode Polling (4s)"]
        FollowCheck["Relationship Check (user_friendship_v1)"]
        DBSync["MongoDB stores user link & chat_id"]
        WorkerQueue["Thread-safe Task Queue"]
        Downloader["yt-dlp + ffmpeg downloads MP4"]
        Uploader["Telegram Bot API sends Video"]
    end

    TG_User --> TG_Code
    TG_Code --> FastPoll
    TG_Code -.-> IG_Follow
    IG_Follow --> IG_DM
    IG_DM --> FollowCheck
    FollowCheck --> DBSync
    DBSync --> IG_Reply
    DBSync --> TG_Success
    IG_SendReel --> WorkerQueue
    WorkerQueue --> Downloader
    Downloader --> Uploader
    Uploader --> TG_Reel
```

### Detailed Lifecycle:
1. **Registration**: A user sends `/register <username>` or messages their Instagram username to the Telegram bot.
2. **Fast Polling Trigger**: The Telegram bot alerts the Instagram monitor thread to switch to 4-second fast-polling mode for 2 minutes.
3. **Follower Check**: When the user sends `verify RG-XXXXXX` on Instagram, the bot uses Instagram's private friendship API (`user_friendship_v1`) to verify that the user follows [@reelgram_sync](https://www.instagram.com/reelgram_sync/).
4. **Confirmation**:
   - The bot replies directly in Instagram DM: `"✅ Account Verified!"`.
   - The bot sends a confirmation message to the user's Telegram chat.
5. **Reel Processing**:
   - The user shares any Reel to the bot's Instagram DM.
   - The monitor thread extracts the Reel URL, validates the sender, and enqueues the task.
   - A downloader worker grabs the video with `yt-dlp` and merges streams via `ffmpeg`.
   - The uploader worker sends the native video directly to the user's Telegram chat.
   - Temporary video files are automatically deleted after successful delivery.

---

## 📋 Prerequisites

Before starting, ensure you have:

- **Python**: Version 3.10 or higher
- **FFmpeg**: Required by `yt-dlp` for video stream extraction and audio merging
- **MongoDB**: A free cloud database cluster from [MongoDB Atlas](https://www.mongodb.com/atlas) or a local MongoDB server
- **Telegram Bot**: Created via [@BotFather](https://t.me/BotFather)
- **Instagram Account**: Dedicated bot account (e.g. [@reelgram_sync](https://www.instagram.com/reelgram_sync/))

---

## 🚀 Setup & Installation

### 1. Clone Repository

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

### 4. Install FFmpeg

- **Windows**:
  ```powershell
  winget install Gyan.FFmpeg
  # Or with Chocolatey:
  choco install ffmpeg
  ```
- **Ubuntu / Debian**:
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```
- **macOS** (Homebrew):
  ```bash
  brew install ffmpeg
  ```

---

## ⚙️ Configuration (.env)

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Fill in your configuration variables:

| Variable | Description | Required | Example |
|---|---|:---:|---|
| `INSTAGRAM_USERNAME` | Instagram handle of your bot account | **Yes** | `reelgram_sync` |
| `INSTAGRAM_PASSWORD` | Password for your Instagram bot account | **Yes** | `YourSecurePassword123` |
| `INSTAGRAM_SESSION_ID` | Session ID cookie (optional fallback) | No | `64603757963%3A...` |
| `TELEGRAM_BOT_TOKEN` | Token obtained from [@BotFather](https://t.me/BotFather) | **Yes** | `123456789:ABCdefGHIjkl...` |
| `TELEGRAM_CHAT_ID` | Fallback chat ID for unmapped Reels | No | `1342641151` |
| `MONGODB_URI` | MongoDB connection URI | **Yes** | `mongodb+srv://user:pass@cluster0...` |
| `MONGODB_DB_NAME` | Database name | No | `reelgram` |
| `OWNER_ID` | Your Telegram user ID (for admin commands) | **Yes** | `1342641151` |
| `DEVELOPER_USERNAME` | Developer handle shown in `/developer` | No | `MrTG_Coder` |
| `FORCE_SUB_INSTAGRAM` | Require users to follow the bot on Instagram | No | `true` |
| `FORCE_SUB_CHANNEL_ID` | Telegram channel ID for forced Telegram join | No | `-1001234567890` |
| `FORCE_SUB_INVITE_LINK` | Invite link for forced Telegram join | No | `https://t.me/your_channel` |
| `DOWNLOAD_PATH` | Path where temporary videos are stored | No | `downloads/` |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) | No | `INFO` |

> [!TIP]
> **Instagram Session Persistence**: On your first successful login, ʀᴇᴇʟɢʀᴀᴍ dumps the session state into `session.json`. Subsequent starts restore this session directly, avoiding repeated logins, SMS challenges, or checkpoint blocks.

---

## 🏃 Running the Bot

Start the unified daemon:

```bash
python main.py
```

You will see the startup banner and three background threads initializing:
1. `InstagramMonitorThread` — Checks direct inbox and pending message requests.
2. `WorkerThread-1` & `WorkerThread-2` — Concurrently download and deliver Reels.
3. `TelegramRegistrationBot` — Handles user interactions, commands, and admin features.

---

## 📖 Usage Guide

### 📱 For Regular Users

1. **Start the Bot**: Open your Telegram bot and send `/start`.
2. **Follow on Instagram**: Follow the bot account ([@reelgram_sync](https://www.instagram.com/reelgram_sync/)).
3. **Link Your Account**:
   - Send `/register <your_instagram_username>` or simply message your Instagram handle directly.
   - The bot replies with a verification code: `verify RG-XXXXXX`.
4. **Verify in Instagram DM**:
   - Open Instagram, go to [@reelgram_sync](https://www.instagram.com/reelgram_sync/), and DM:
     ```
     verify RG-XXXXXX
     ```
   - You will immediately receive a confirmation DM on Instagram and an alert on Telegram.
5. **Receive Reels**:
   - Share or DM any Instagram Reel to [@reelgram_sync](https://www.instagram.com/reelgram_sync/).
   - ʀᴇᴇʟɢʀᴀᴍ will download the Reel and send it directly to your Telegram chat!

### 👤 User Commands

| Command | Description |
|---|---|
| `/start` | Open the interactive main menu |
| `/register <username>` | Generate a verification code to link an Instagram account |
| `/status` | Check your linked Instagram account and status |
| `/unlink` | Unlink your Instagram account from Telegram |
| `/help` | View the step-by-step user guide |
| `/developer` | Contact details of the bot developer |

---

### 👑 For Bot Owners (Admin Panel)

As the configured `OWNER_ID`, you have access to real-time administrative controls:

#### 1. Interactive Stats Dashboard (`/stats`)
Displays real-time analytics:
- 👥 **Total Registered Users**: Total Telegram users who started the bot.
- 🔗 **Verified Instagram Accounts**: Number of successfully linked profiles.
- 📥 **Pending Verifications**: Codes awaiting verification in DM.
- 🎬 **Total Reels Processed**: Cumulative count of Reels downloaded & delivered.
- 📅 **Reels Delivered Today**: Feature usage for the current UTC day.
- ⚡ **Queue Status**: Live pending download tasks.

#### 2. User Inspector (`/users`)
View the latest 10 users with their linked Instagram usernames, join dates, and delivered Reel counts.

#### 3. Mass Broadcast (`/broadcast`)
Send announcements to all bot users:
1. Send `/broadcast`.
2. Reply with the message, photo, video, or formatted text you want to broadcast.
3. The bot sends the broadcast with a live progress indicator and 30 msg/sec rate limiting.
4. Send `/cancel` at any time to cancel.

#### 4. Real-Time User Alerts
Whenever a new user starts the bot, the owner receives an instant alert on Telegram with user details (`ID`, `Username`, `Name`).

---

## 🐳 Docker Deployment

A production-ready `Dockerfile` is included:

```bash
# Build Docker image
docker build -t reelgram .

# Run container with environment file
docker run -d \
  --name reelgram \
  --restart always \
  --env-file .env \
  reelgram
```

---

## 🚄 Railway Deployment

ReelGram runs 24/7 background worker daemons and long-polling threads, making Railway or a VPS the ideal hosting environment (serverless platforms like Vercel are not supported due to execution timeouts and lack of persistent background threads).

1. Push your repository to GitHub.
2. Sign in to [Railway](https://railway.app) and create a **New Project**.
3. Select **Deploy from GitHub repo** and choose your repository.
4. Go to **Variables** in Railway and add the environment keys from `.env.example`.
5. Railway will automatically build the `Dockerfile` and start the bot with restart-on-failure enabled (`railway.json`).

---

## 📂 Project Structure

```
Reel-Gram/
├── main.py                  # Orchestrator & multi-threaded signal runner
├── config.py                # Environment configuration & logging setup
├── requirements.txt         # Project dependencies
├── Dockerfile               # Production Docker container build
├── railway.json             # Railway hosting configuration
├── .env.example             # Template for environment variables
├── session.json             # Cached Instagram session (auto-generated)
│
├── instagram/
│   ├── login.py             # Instagrapi authentication & session caching
│   ├── monitor.py           # Inbox polling, fast-mode triggers & auto-approval
│   ├── handler.py           # Message routing, follow verification & DM replies
│   ├── extractor.py         # Multi-type Reel URL extraction
│   └── parser.py            # Direct message payload parser
│
├── downloader/
│   ├── download.py          # yt-dlp video downloader engine
│   ├── validator.py         # URL format & domain validation
│   └── cleaner.py           # Post-upload file cleanup utility
│
├── telegram_bot/
│   ├── registration_bot.py  # Telegram bot handlers, /stats, /users, broadcast
│   ├── sender.py            # Telegram video delivery wrapper
│   └── uploader.py          # Upload queue dispatcher
│
├── database/
│   ├── db.py                # MongoDB singleton connection manager
│   └── models.py            # MongoDB schemas, analytics & query functions
│
├── assets/                  # Brand assets & generated logo variations
├── downloads/               # Temporary video download directory (ephemeral)
└── logs/                    # Application log files
```

---

## 🔧 Troubleshooting & FAQ

<details>
<summary><b>1. Instagram asks for a challenge / 2FA checkpoint?</b></summary>
Log into the bot's Instagram account on a mobile browser or desktop browser from the same IP if possible. If 2FA is enabled, grab the <code>sessionid</code> cookie from your browser's Developer Tools and place it into <code>INSTAGRAM_SESSION_ID</code> in <code>.env</code>. Once the bot runs once, it will save <code>session.json</code> and never ask again.
</details>

<details>
<summary><b>2. Bot says "Follow Required" even after I followed?</b></summary>
Instagram's search index can take a few minutes to index new followers. ʀᴇᴇʟɢʀᴀᴍ uses a multi-method check (direct relationship API + followers list). If you followed after receiving the warning, simply send <code>verify RG-XXXXXX</code> again in the DM and the bot will verify immediately.
</details>

<details>
<summary><b>3. Why can't this be hosted on Vercel?</b></summary>
Vercel is designed for serverless HTTP request-response handlers that terminate after 10-60 seconds. ʀᴇᴇʟɢʀᴀᴍ requires persistent daemons (Instagram polling loop, task queues, and Telegram long-polling) as well as a local FFmpeg binary. Use Railway, Docker, or any Linux VPS.
</details>

---

## 👨‍💻 Author & Credits

Developed with ❤️ by **Amal Nath**

- **Telegram**: [@MrTG_Coder](https://t.me/MrTG_Coder)
- **Instagram**: [@amal_.nath_](https://www.instagram.com/amal_.nath_/)
- **Bot Instagram**: [@reelgram_sync](https://www.instagram.com/reelgram_sync/)

---

## 📄 License

This project is open-source and intended for personal automation and educational purposes. Ensure compliance with Instagram's and Telegram's respective Terms of Service.
