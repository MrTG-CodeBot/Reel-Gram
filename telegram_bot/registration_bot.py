import asyncio
import re
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
from database.models import (
    create_pending_registration,
    get_registration_by_telegram,
    unlink_user_by_telegram,
    track_user,
    get_all_user_chat_ids,
    get_user_count,
    get_db_stats,
    get_bot_owner_stats,
    get_recent_users
)
from config import (
    TELEGRAM_BOT_TOKEN,
    FORCE_SUB_CHANNEL_ID,
    FORCE_SUB_INVITE_LINK,
    DEVELOPER_USERNAME,
    INSTAGRAM_USERNAME,
    OWNER_ID,
    LOG_CHANNEL_ID,
    logger
)
import threading

# In-memory state for broadcast mode: {owner_chat_id: True}
_broadcast_mode = {}

def _format_size(size_bytes: int) -> str:
    """Formats byte size into a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"

# Helper to check if a user is subscribed to the required channel/group
async def is_user_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not FORCE_SUB_CHANNEL_ID:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=FORCE_SUB_CHANNEL_ID, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except TelegramError as e:
        logger.warning(f"Error checking channel membership for user {user_id}: {e}. "
                       "Ensure the bot is added as an administrator to the target channel. Failing open to prevent blocking.")
        return True
    except Exception as e:
        logger.warning(f"Unexpected error checking channel membership: {e}. Failing open.")
        return True

# Forces the user to join the channel
async def send_force_sub_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📢 <b>Subscription Required</b>\n\n"
        "You must join our channel/group to use this bot's services!\n"
        "Please subscribe and click <b>Check Joined</b> below to unlock all premium features."
    )
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=FORCE_SUB_INVITE_LINK)],
        [InlineKeyboardButton("🔄 Check Joined", callback_data="check_joined")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")

# Main Start Page Markup
def get_start_markup(user_id: int = None) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔑 Link Account", callback_data="show_link_info"),
            InlineKeyboardButton("📊 My Status", callback_data="show_status")
        ],
        [
            InlineKeyboardButton("ℹ️ Help & Guide", callback_data="show_help"),
            InlineKeyboardButton("💻 Developer", callback_data="show_developer")
        ]
    ]
    # Show admin button only for the owner
    if user_id and user_id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="show_admin")])
    return InlineKeyboardMarkup(keyboard)


async def notify_new_user_if_needed(user, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Checks if a user is newly seen. If yes, tracks them in database and sends a formatted alert
    with name, username (or None), user id, and permanent link to the configured log channel and owner.
    """
    if not user:
        return False
        
    chat_id = str(user.id)
    is_new = track_user(chat_id, first_name=user.first_name, username=user.username)
    if not is_new:
        return False

    user_name = user.full_name or user.first_name or "Anonymous"
    username_str = f"@{user.username}" if user.username else "None"
    perm_link = f"tg://user?id={user.id}"
    total = get_user_count()

    alert_text = (
        "👤 <b>#NewUser Started ʀᴇᴇʟɢʀᴀᴍ!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Name:</b> <a href=\"{perm_link}\">{html.escape(user_name)}</a>\n"
        f"• <b>Username:</b> {username_str}\n"
        f"• <b>User ID:</b> <code>{user.id}</code>\n"
        f"• <b>Permanent Link:</b> <a href=\"{perm_link}\">{perm_link}</a>\n"
        f"• <b>Total Users:</b> <b>{total}</b>"
    )

    # 1. Send to configured log channel (from .env LOG_CHANNEL_ID)
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(
                chat_id=LOG_CHANNEL_ID,
                text=alert_text,
                parse_mode="HTML"
            )
            logger.info(f"Broadcasted new user alert to log channel {LOG_CHANNEL_ID} for user {user.id}")
        except Exception as e:
            logger.warning(f"Failed to send new user alert to channel {LOG_CHANNEL_ID}: {e}")

    # 2. Also notify bot owner if OWNER_ID configured and distinct from log channel
    if OWNER_ID and user.id != OWNER_ID and str(OWNER_ID) != str(LOG_CHANNEL_ID):
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=alert_text,
                parse_mode="HTML"
            )
        except Exception as oe:
            logger.debug(f"Could not send new user alert to owner {OWNER_ID}: {oe}")

    return True

# Start command
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return
    
    # Track user in database and broadcast new user alert to log channel / owner
    user = update.effective_user
    await notify_new_user_if_needed(user, context)
        
    text = (
        "✨ <b>ʀᴇᴇʟɢʀᴀᴍ — Reel Automation Bot</b> ✨\n\n"
        "I can automatically download and deliver Instagram Reels sent to our Instagram DM directly to your Telegram chat.\n\n"
        "👇 Choose an option below to get started:"
    )
    await update.message.reply_text(text, reply_markup=get_start_markup(user_id), parse_mode="HTML")

# Help command
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return
        
    ig_bot = f'<a href="https://instagram.com/{INSTAGRAM_USERNAME}">@{INSTAGRAM_USERNAME}</a>' if INSTAGRAM_USERNAME else "@our_bot_account"
    text = (
        "ℹ️ <b>ʀᴇᴇʟɢʀᴀᴍ — User Guide</b>\n\n"
        "1️⃣ Follow our Instagram account (" + ig_bot + ") & link using <code>/register &lt;username&gt;</code>.\n"
        "2️⃣ DM any Reel to our Instagram account (" + ig_bot + ").\n"
        "3️⃣ ʀᴇᴇʟɢʀᴀᴍ will detect, download, and send the Reel directly to this chat.\n\n"
        "<b>Commands Reference:</b>\n"
        "• <code>/register &lt;username&gt;</code> - Link your Instagram username\n"
        "• <code>/status</code> - Check verification/linking status\n"
        "• <code>/unlink</code> - Remove active account link"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# Developer command
async def developer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return
        
    text = (
        "💻 <b>Developer Details</b>\n\n"
        "This bot was created and is maintained by <b>Amal Nath</b>.\n\n"
        "• <b>Telegram:</b> @MrTG_Coder\n"
        "• <b>Instagram:</b> <a href=\"https://instagram.com/amal_.nath_\">@amal_.nath_</a>\n\n"
        "Click the buttons below to visit the developer profiles:"
    )
    keyboard = [
        [
            InlineKeyboardButton("💬 Telegram", url="https://t.me/MrTG_Coder"),
            InlineKeyboardButton("📸 Instagram", url="https://instagram.com/amal_.nath_")
        ],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# Stats command (owner only)
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ This command is restricted to the bot owner.")
        return
    await send_stats_message(update)

async def send_stats_message(update: Update) -> None:
    stats = get_bot_owner_stats()
    if not stats:
        err_msg = "❌ Failed to compile bot statistics. Ensure MongoDB is running and connected."
        if update.message:
            await update.message.reply_text(err_msg)
        elif update.callback_query:
            await update.callback_query.message.reply_text(err_msg)
        return

    db_stats = stats.get("db_stats", {})
    data_size = _format_size(db_stats.get("dataSize", 0))
    storage_size = _format_size(db_stats.get("storageSize", 0))
    free_size = _format_size(db_stats.get("freeStorageSize", 0))

    text = (
        "⚙️ <b>ʀᴇᴇʟɢʀᴀᴍ — Bot Analytics & Stats</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 <b>User Base:</b>\n"
        f"• Total Users (Started): <b>{stats['total_users']}</b>\n"
        f"• New Today (24h): <b>+{stats['new_users_24h']}</b>\n"
        f"• Active Today (24h): <b>{stats['active_users_24h']}</b>\n"
        f"• Active This Week (7d): <b>{stats['active_users_7d']}</b>\n\n"
        "🔗 <b>Instagram Connections:</b>\n"
        f"• Connected (Verified): <b>{stats['connected_users']}</b> ({stats['connection_rate']}%)\n"
        f"• Pending Verification: <b>{stats['pending_users']}</b>\n\n"
        "🚀 <b>Feature Usage & Deliveries:</b>\n"
        f"• Users Receiving Reels: <b>{stats['feature_users']}</b>\n"
        f"• Unique IG Senders: <b>{stats['unique_ig_senders']}</b>\n"
        f"• Total Reels Tracked: <b>{stats['total_reels']}</b>\n"
        f"  ├─ ✅ Completed: <b>{stats['completed_reels']}</b> ({stats['success_rate']}%)\n"
        f"  ├─ ⏳ In-Flight: <b>{stats['in_flight_reels']}</b>\n"
        f"  └─ ❌ Failed: <b>{stats['failed_reels']}</b>\n\n"
        "💾 <b>Database & Storage:</b>\n"
        f"• Storage Used: <b>{storage_size}</b> (Data: {data_size})\n"
        f"• Free Storage: <b>{free_size}</b>\n"
        f"• Collections: <b>{db_stats.get('collections', 0)}</b> | Objects: <b>{db_stats.get('objects', 0)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <i>Last Updated: {stats['timestamp']} UTC</i>"
    )
    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="refresh_stats"),
            InlineKeyboardButton("👥 Recent Users", callback_data="admin_recent_users")
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("🔙 Back to Admin", callback_data="show_admin")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        try:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            pass

# Users command (owner only)
async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ This command is restricted to the bot owner.")
        return
    await send_recent_users_message(update)

async def send_recent_users_message(update: Update) -> None:
    users = get_recent_users(limit=10)
    if not users:
        text = "👥 <b>Recent Users</b>\n\nNo registered users found in the database yet."
    else:
        text = "👥 <b>Recent Active Users (Latest 10)</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for idx, u in enumerate(users, 1):
            name = u.get("first_name") or "Anonymous"
            uname = f"@{u['username']}" if u.get("username") else "No username"
            tg_id = u.get("telegram_chat_id", "Unknown")
            ig = u.get("linked_instagram")
            ig_str = f"✅ Linked: @{ig}" if ig else "❌ Not linked"
            reels = u.get("reels_received", 0)
            seen = u.get("last_seen")
            seen_str = seen.strftime("%b %d, %H:%M") if hasattr(seen, "strftime") else "Recently"
            
            text += f"<b>{idx}. {name}</b> ({uname})\n"
            text += f"   • Chat ID: <code>{tg_id}</code>\n"
            text += f"   • Instagram: {ig_str}\n"
            text += f"   • Reels Received: <b>{reels}</b> | Seen: {seen_str}\n\n"

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh List", callback_data="admin_recent_users"),
            InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats")
        ],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="show_admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        try:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            pass

# Broadcast command (owner only)
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ This command is restricted to the bot owner.")
        return
    
    chat_id = str(update.effective_chat.id)
    _broadcast_mode[chat_id] = True
    text = (
        "📢 <b>Broadcast Mode Activated</b>\n\n"
        "Send your next message (text, photo, video, etc.) and it will be <b>copied</b> to all bot users.\n\n"
        "Send /cancel to exit broadcast mode."
    )
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# Cancel command
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = str(update.effective_chat.id)
    if chat_id in _broadcast_mode:
        del _broadcast_mode[chat_id]
        await update.message.reply_text("✅ Broadcast mode cancelled.")
    else:
        await update.message.reply_text("Nothing to cancel.")

# Register command
async def register_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return
        
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/register &lt;your_instagram_username&gt;</code>\nExample: <code>/register my_username</code>\n\nOr just send your username directly.", parse_mode="HTML")
        return
        
    instagram_username = context.args[0].strip().lower().replace("@", "").strip(".")
    await execute_registration_flow(update, instagram_username, chat_id, context)

async def execute_registration_flow(update: Update, instagram_username: str, chat_id: str, context: ContextTypes.DEFAULT_TYPE = None):
    try:
        user = update.effective_user
        if user and context:
            await notify_new_user_if_needed(user, context)
        elif user:
            track_user(chat_id, first_name=user.first_name, username=user.username)
        code = create_pending_registration(instagram_username, chat_id)
        
        # Trigger fast Instagram polling so verification happens within seconds
        try:
            from instagram.monitor import notify_registration_started
            notify_registration_started()
        except Exception as e:
            logger.debug(f"Could not notify monitor for fast registration: {e}")

        ig_profile = f'<a href="https://www.instagram.com/{instagram_username}">https://www.instagram.com/{instagram_username}</a>'
        ig_bot = f'<a href="https://www.instagram.com/{INSTAGRAM_USERNAME}">https://www.instagram.com/{INSTAGRAM_USERNAME}</a>' if INSTAGRAM_USERNAME else "@our_bot_account"
        text = (
            f"🔑 <b>Verification Code:</b> <code>verify {code}</code>\n\n"
            f"Please verify your ownership of {ig_profile} to link it:\n\n"
            f"1. 👉 <b>Follow our Instagram:</b> {ig_bot}\n"
            f"2. DM <code>verify {code}</code> to {ig_bot}\n\n"
            f"⚠️ <i>You must follow {ig_bot} on Instagram to use ʀᴇᴇʟɢʀᴀᴍ services!</i>\n"
            f"⏳ This code will expire in <b>10 minutes</b>."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]
        
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in register command: {e}")
        error_msg = "❌ An error occurred while generating your verification code. Please try again."
        if update.message:
            await update.message.reply_text(error_msg)
        elif update.callback_query:
            await update.callback_query.message.reply_text(error_msg)

# Status command
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return
        
    chat_id = str(update.effective_chat.id)
    await show_user_status(update, chat_id)

async def show_user_status(update: Update, chat_id: str):
    try:
        reg = get_registration_by_telegram(chat_id)
        keyboard = []
        if reg:
            username = reg.get("instagram_username")
            verified = reg.get("verified")
            if verified:
                text = f"✅ <b>Linked Account Status</b>\n\n• <b>Instagram:</b> <a href=\"https://www.instagram.com/{username}\">https://www.instagram.com/{username}</a>\n• <b>Status:</b> Verified and active"
                keyboard.append([InlineKeyboardButton("❌ Unlink Account", callback_data="confirm_unlink")])
            else:
                code = reg.get("verification_code")
                text = (
                    f"⚠️ <b>Verification Pending</b>\n\n"
                    f"• <b>Instagram:</b> <a href=\"https://www.instagram.com/{username}\">https://www.instagram.com/{username}</a>\n"
                    f"• <b>Verification Code:</b> <code>verify {code}</code>\n\n"
                    f"Send <code>verify {code}</code> to the Instagram bot to link."
                )
                keyboard.append([InlineKeyboardButton("🔄 Verify/Retry Link", callback_data="show_link_info")])
        else:
            text = "❌ <b>No Instagram account linked to this chat.</b>\n\nUse /register or click the button below to link one."
            keyboard.append([InlineKeyboardButton("🔑 Link Account", callback_data="show_link_info")])
            
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")])
        
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in status logic: {e}")
        err_msg = "❌ Failed to fetch registration status."
        if update.message:
            await update.message.reply_text(err_msg)
        elif update.callback_query:
            await update.callback_query.message.reply_text(err_msg)

# Unlink command
async def unlink_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return
        
    chat_id = str(update.effective_chat.id)
    await execute_unlink(update, chat_id)

async def execute_unlink(update: Update, chat_id: str):
    try:
        reg = get_registration_by_telegram(chat_id)
        if reg:
            username = reg.get("instagram_username")
            unlink_user_by_telegram(chat_id)
            text = f"✅ Successfully unlinked Instagram account @{username}."
        else:
            text = "❌ No Instagram account is linked to this chat."
            
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]
        
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in unlink logic: {e}")
        err_msg = "❌ Failed to unlink account."
        if update.message:
            await update.message.reply_text(err_msg)
        elif update.callback_query:
            await update.callback_query.message.reply_text(err_msg)

# Callback Query Handler
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    if not update.effective_user or not update.effective_chat:
        return
    user_id = update.effective_user.id
    chat_id = str(update.effective_chat.id)
    data = query.data
    
    # Bypass sub check if it's the verify/check callback
    if data == "check_joined":
        if await is_user_subscribed(user_id, context):
            text = (
                "✨ <b>ʀᴇᴇʟɢʀᴀᴍ — Reel Automation Bot</b> ✨\n\n"
                "I can automatically download and deliver Instagram Reels sent to our Instagram DM directly to your Telegram chat.\n\n"
                "👇 Choose an option below to get started:"
            )
            await query.message.edit_text(text, reply_markup=get_start_markup(user_id), parse_mode="HTML")
            await query.answer("✅ Success! Channel subscription verified.", show_alert=True)
        else:
            await query.answer("❌ You have not joined the channel yet! Please subscribe first.", show_alert=True)
        return

    # Cancel broadcast mode
    if data == "cancel_broadcast":
        if chat_id in _broadcast_mode:
            del _broadcast_mode[chat_id]
        await query.message.edit_text("✅ Broadcast mode cancelled.")
        return

    # Check force sub for other button callbacks
    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return
        
    if data == "show_start":
        text = (
            "✨ <b>ʀᴇᴇʟɢʀᴀᴍ — Reel Automation Bot</b> ✨\n\n"
            "I can automatically download and deliver Instagram Reels sent to our Instagram DM directly to your Telegram chat.\n\n"
            "👇 Choose an option below to get started:"
        )
        await query.message.edit_text(text, reply_markup=get_start_markup(user_id), parse_mode="HTML")
        
    elif data == "show_link_info":
        text = (
            "🔑 <b>Link Instagram Account</b>\n\n"
            "Please link your Instagram account using command:\n"
            "<code>/register &lt;your_instagram_username&gt;</code>\n\n"
            "Or reply with your username directly to verify."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif data == "show_status":
        await show_user_status(update, chat_id)
        
    elif data == "show_help":
        ig_bot = f'<a href="https://instagram.com/{INSTAGRAM_USERNAME}">@{INSTAGRAM_USERNAME}</a>' if INSTAGRAM_USERNAME else "@our_bot_account"
        text = (
            "ℹ️ <b>ʀᴇᴇʟɢʀᴀᴍ — User Guide</b>\n\n"
            "1️⃣ Follow our Instagram account (" + ig_bot + ") & link using <code>/register &lt;username&gt;</code>.\n"
            "2️⃣ DM any Reel to our Instagram account (" + ig_bot + ").\n"
            "3️⃣ ʀᴇᴇʟɢʀᴀᴍ will detect, download, and send the Reel directly to this chat.\n\n"
            "<b>Commands Reference:</b>\n"
            "• <code>/register &lt;username&gt;</code> - Link your Instagram username\n"
            "• <code>/status</code> - Check verification/linking status\n"
            "• <code>/unlink</code> - Remove active account link"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif data == "show_developer":
        text = (
            "💻 <b>Developer Details</b>\n\n"
            "This bot was created and is maintained by <b>Amal Nath</b>.\n\n"
            "• <b>Telegram:</b> @MrTG_Coder\n"
            "• <b>Instagram:</b> <a href=\"https://instagram.com/amal_.nath_\">@amal_.nath_</a>\n\n"
            "Click the buttons below to visit the developer profiles:"
        )
        keyboard = [
            [
                InlineKeyboardButton("💬 Telegram", url="https://t.me/MrTG_Coder"),
                InlineKeyboardButton("📸 Instagram", url="https://instagram.com/amal_.nath_")
            ],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "show_admin":
        if user_id != OWNER_ID:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        text = (
            "⚙️ <b>Admin Panel</b>\n\n"
            "Choose an admin action below:"
        )
        keyboard = [
            [
                InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats"),
                InlineKeyboardButton("👥 Recent Users", callback_data="admin_recent_users")
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")
            ]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "admin_stats":
        if user_id != OWNER_ID:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        await send_stats_message(update)

    elif data == "refresh_stats":
        if user_id != OWNER_ID:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        await send_stats_message(update)
        await query.answer("✅ Stats refreshed!")

    elif data == "admin_recent_users":
        if user_id != OWNER_ID:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        await send_recent_users_message(update)

    elif data == "admin_broadcast":
        if user_id != OWNER_ID:
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        _broadcast_mode[chat_id] = True
        text = (
            "📢 <b>Broadcast Mode Activated</b>\n\n"
            "Send your next message (text, photo, video, etc.) and it will be <b>copied</b> to all bot users.\n\n"
            "Send /cancel to exit broadcast mode."
        )
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif data == "confirm_unlink":
        text = "⚠️ <b>Are you sure you want to unlink your Instagram account from this Telegram chat?</b>"
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Unlink", callback_data="do_unlink"),
                InlineKeyboardButton("❌ Cancel", callback_data="show_status")
            ]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif data == "do_unlink":
        await execute_unlink(update, chat_id)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat or not update.message:
        return
    user_id = update.effective_user.id
    chat_id = str(update.effective_chat.id)

    # Check if owner is in broadcast mode
    if chat_id in _broadcast_mode and user_id == OWNER_ID:
        del _broadcast_mode[chat_id]
        await execute_broadcast(update, context)
        return

    if not await is_user_subscribed(user_id, context):
        await send_force_sub_message(update, context)
        return

    text = update.message.text.strip()
    # Instagram username validation: alphanumeric, periods, underscores, 1-30 chars
    username_clean = text.lower().replace("@", "").strip().strip(".")
    
    if re.match(r"^[a-zA-Z0-9._]{1,30}$", username_clean):
        logger.info(f"Plaintext username input detected: '{username_clean}' from TG={chat_id}")
        await execute_registration_flow(update, username_clean, chat_id, context)
    else:
        # If it doesn't look like a username, fall back to start menu
        await start_cmd(update, context)

async def handle_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles non-text messages (photos, videos, etc.) — used for broadcast copy."""
    if not update.effective_user or not update.effective_chat or not update.message:
        return
    user_id = update.effective_user.id
    chat_id = str(update.effective_chat.id)
    
    if chat_id in _broadcast_mode and user_id == OWNER_ID:
        del _broadcast_mode[chat_id]
        await execute_broadcast(update, context)

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Copies the owner's message to all tracked users."""
    msg = update.message
    all_chat_ids = get_all_user_chat_ids()
    total = len(all_chat_ids)
    
    status_msg = await msg.reply_text(f"📢 Broadcasting to {total} users... (0/{total})")
    
    sent = 0
    failed = 0
    
    for i, target_chat_id in enumerate(all_chat_ids):
        try:
            await msg.copy(chat_id=target_chat_id)
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for chat {target_chat_id}: {e}")
            failed += 1
        
        # Update progress every 10 users
        if (i + 1) % 10 == 0:
            try:
                await status_msg.edit_text(f"📢 Broadcasting... ({i + 1}/{total})")
            except Exception:
                pass
        
        # Telegram rate limit safety: 30 messages/second max
        await asyncio.sleep(0.05)
    
    await status_msg.edit_text(
        f"✅ <b>Broadcast Complete</b>\n\n"
        f"• Sent: {sent}\n"
        f"• Failed: {failed}\n"
        f"• Total: {total}",
        parse_mode="HTML"
    )

class RegistrationBot:
    def __init__(self):
        self.app = None
        self.thread = None
        self._loop = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="TelegramRegistrationBot")
        self.thread.daemon = True
        self.thread.start()

    def _run(self) -> None:
        logger.info("Initializing Telegram registration bot...")
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("start", start_cmd))
        self.app.add_handler(CommandHandler("help", help_cmd))
        self.app.add_handler(CommandHandler("developer", developer_cmd))
        self.app.add_handler(CommandHandler("register", register_cmd))
        self.app.add_handler(CommandHandler("status", status_cmd))
        self.app.add_handler(CommandHandler("unlink", unlink_cmd))
        self.app.add_handler(CommandHandler("stats", stats_cmd))
        self.app.add_handler(CommandHandler("users", users_cmd))
        self.app.add_handler(CommandHandler("broadcast", broadcast_cmd))
        self.app.add_handler(CommandHandler("cancel", cancel_cmd))
        self.app.add_handler(CallbackQueryHandler(handle_callback))
        self.app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_message))
        # Handler for non-text messages (photos, videos, etc.) for broadcast in private chat
        self.app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.TEXT & ~filters.COMMAND, handle_non_text_message))
        
        async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            logger.error(f"Telegram handler error: {context.error} (update={update})")
        self.app.add_error_handler(on_error)
        
        logger.info("Telegram registration bot starting polling...")
        self.app.run_polling(stop_signals=None, close_loop=False)

    def stop(self) -> None:
        logger.info("Stopping Telegram registration bot...")
        if self.app and self.app.running:
            try:
                # We must schedule stop inside the thread's event loop
                future = asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop)
                future.result()
                future_shutdown = asyncio.run_coroutine_threadsafe(self.app.shutdown(), self._loop)
                future_shutdown.result()
            except Exception as e:
                logger.error(f"Error stopping registration bot: {e}")
        logger.info("Telegram registration bot stopped.")
