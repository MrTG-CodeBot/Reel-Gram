# 🎬 ReelGram

**Instagram Reels → Telegram, fully automated.**

ReelGram is a self-hosted automation bot that monitors your Instagram DMs for shared Reels, downloads them via `yt-dlp`, and delivers them directly to linked Telegram chats — all in real time. It supports multi-user account linking with a secure verification flow, an admin panel, broadcast messaging, and crash recovery out of the box.

---

## ✨ Features

- **Automatic Reel Detection** — Polls your Instagram inbox and extracts Reel URLs from DMs (including pending message requests).
- **High-Quality Downloads** — Uses `yt-dlp` with `ffmpeg` to grab the best available video quality.
- **Telegram Delivery** — Uploads downloaded Reels directly to the sender's linked Telegram chat via the Bot API.
- **Multi-User Support** — Any Telegram user can link their Instagram account and receive their own Reels privately.
- **Secure Verification** — Time-limited `RG-XXXXXX` codes verified through Instagram DM to prove account ownership.
- **Crash Recovery** — On restart, pending/incomplete tasks are re-queued automatically from MongoDB.
- **Admin Panel** — Bot owner gets stats, user counts, database metrics, and broadcast capabilities.
- **Force Subscribe** — Optionally require users to join a Telegram channel before using the bot.
- **Docker & Railway Ready** — Ships with a `Dockerfile` and `railway.json` for one-click cloud deployment.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│                        main.py                           │
│              (Orchestrator & Signal Handler)              │
├────────────┬────────────────────────┬────────────────────┤
│            │                        │                    │
│  Instagram Monitor         Worker Pool (x2)    Telegram Bot
│  (Polling Thread)       (Download & Upload)   (Registration)
│            │                        │                    │
│  instagram/                downloader/          telegram_bot/
│  ├── login.py              ├── download.py      ├── registration_bot.py
│  ├── monitor.py            ├── validator.py     ├── sender.py
│  ├── handler.py            └── cleaner.py       └── uploader.py
│  ├── extractor.py
│  └── parser.py
│            │                        │                    │
│            └────────────┬───────────┘                    │
│                         │                                │
│                    database/                             │
│                    ├── db.py (MongoDB client)            │
│                    └── models.py (Data layer)            │
└──────────────────────────────────────────────────────────┘
```

**Flow:**
1. `InstagramMonitor` polls the Instagram inbox every 30 seconds.
2. New Reel URLs are extracted and pushed to a thread-safe `Queue`.
3. Worker threads pick up tasks, download via `yt-dlp`, and upload to Telegram.
4. The `RegistrationBot` handles user commands (`/register`, `/status`, `/unlink`) on Telegram.

---

## 📋 Prerequisites

- **Python** 3.10+
- **MongoDB** (local or [MongoDB Atlas](https://www.mongodb.com/atlas))
- **FFmpeg** (required by `yt-dlp` for video merging)
- **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))
- **Instagram Account** (the bot account that receives DMs)

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-username/reelgram.git
cd reelgram
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `INSTAGRAM_USERNAME` | ✅ | Bot's Instagram username |
| `INSTAGRAM_PASSWORD` | ✅* | Instagram password (*or* provide `INSTAGRAM_SESSION_ID`) |
| `INSTAGRAM_SESSION_ID` | ✅* | Session cookie fallback if password login is blocked |
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | Default Telegram chat/channel for unlinked users |
| `MONGODB_URI` | ❌ | MongoDB connection string (default: `mongodb://localhost:27017`) |
| `MONGODB_DB_NAME` | ❌ | Database name (default: `reelgram`) |
| `DOWNLOAD_PATH` | ❌ | Temp download directory (default: `downloads/`) |
| `LOG_LEVEL` | ❌ | Logging verbosity: `DEBUG`, `INFO`, `WARNING` (default: `INFO`) |
| `FORCE_SUB_CHANNEL_ID` | ❌ | Telegram channel/group ID for forced subscription |
| `FORCE_SUB_INVITE_LINK` | ❌ | Invite link for the force-sub channel |
| `DEVELOPER_USERNAME` | ❌ | Developer's Telegram username shown in `/developer` |
| `OWNER_ID` | ❌ | Telegram user ID of the bot owner (enables admin commands) |

### 4. Run

```bash
python main.py
```

---

## 🐳 Docker

```bash
docker build -t reelgram .
docker run -d --name reelgram --env-file .env reelgram
```

---

## 🚄 Deploy on Railway

1. Fork/push this repo to GitHub.
2. Create a new project on [Railway](https://railway.app).
3. Connect your GitHub repo — Railway will auto-detect the `Dockerfile`.
4. Add all environment variables from `.env.example` in the Railway dashboard.
5. Deploy. Railway will build and run the container automatically.

The included `railway.json` is preconfigured with `restartPolicyType: ON_FAILURE` for resilience.

---

## 🤖 Telegram Bot Commands

### User Commands
| Command | Description |
|---|---|
| `/start` | Show the main menu |
| `/register <username>` | Link your Instagram account |
| `/status` | Check your account linking status |
| `/unlink` | Remove your linked Instagram account |
| `/help` | Show usage guide |
| `/developer` | Developer contact info |

### Owner-Only Commands
| Command | Description |
|---|---|
| `/stats` | View bot statistics and database metrics |
| `/broadcast` | Send a message to all bot users |
| `/cancel` | Cancel an active broadcast |

---

## 🔐 How Account Linking Works

1. User sends `/register my_instagram` on Telegram.
2. Bot generates a time-limited code (e.g., `RG-482910`) valid for 10 minutes.
3. User DMs that code to the bot's Instagram account.
4. ReelGram verifies the code and links the Instagram ↔ Telegram accounts.
5. All future Reels sent by that Instagram user are routed to their personal Telegram chat.

---

## 📁 Project Structure

```
reelgram/
├── main.py                  # Entry point & orchestrator
├── config.py                # Environment config & logging setup
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container build instructions
├── railway.json             # Railway deployment config
├── .env.example             # Environment variable template
│
├── instagram/
│   ├── login.py             # Instagram authentication (password + session)
│   ├── monitor.py           # Inbox polling & DM request auto-approval
│   ├── handler.py           # Message event processing
│   ├── extractor.py         # Reel URL extraction from DM payloads
│   └── parser.py            # Message content parsing
│
├── downloader/
│   ├── download.py          # yt-dlp video downloader
│   ├── validator.py         # URL validation
│   └── cleaner.py           # Temp file cleanup
│
├── telegram_bot/
│   ├── registration_bot.py  # Full Telegram bot (commands, callbacks, broadcast)
│   ├── sender.py            # Video upload to Telegram chats
│   └── uploader.py          # Upload utilities
│
├── database/
│   ├── db.py                # MongoDB client singleton
│   └── models.py            # Data access layer (reels, registrations, users)
│
├── downloads/               # Temporary video storage (auto-created)
└── logs/                    # Application logs (auto-created)
```

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| Instagram API | [instagrapi](https://github.com/subzeroid/instagrapi) |
| Video Downloader | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| Telegram Bot | [python-telegram-bot](https://python-telegram-bot.org/) v20+ |
| Database | [MongoDB](https://www.mongodb.com/) via PyMongo |
| Runtime | Python 3.10+ with threading |
| Deployment | Docker, Railway |

---

## 📝 License

This project is for personal/educational use. See [LICENSE](LICENSE) for details.

---

## 👨‍💻 Author

**Amal Nath**
- Telegram: [@MrTG_Coder](https://t.me/MrTG_Coder)
- Instagram: [@amal_.nath_](https://instagram.com/amal_.nath_)