import asyncio
import re
import html
from typing import Optional, List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError, BadRequest
from database.models import (
    create_pending_registration,
    get_registration_by_telegram,
    get_registrations_by_telegram,
    get_verified_registrations,
    unlink_user_by_telegram,
    track_user,
    get_all_user_chat_ids,
    get_user_count,
    get_db_stats,
    get_bot_owner_stats,
    get_recent_users,
    get_all_users_detailed
)
from config import (
    TELEGRAM_BOT_TOKEN,
    FORCE_SUB_CHANNEL_ID,
    FORCE_SUB_INVITE_LINK,
    DEVELOPER_USERNAME,
    INSTAGRAM_USERNAME,
    OWNER_ID,
    ADMIN_IDS,
    is_admin,
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
    if is_admin(user_id):
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=FORCE_SUB_CHANNEL_ID, user_id=user_id)
        status = getattr(member, "status", "")
        if status in ["member", "administrator", "creator", "owner"]:
            return True
        elif status == "restricted" and getattr(member, "is_member", False):
            return True
        elif status in ["left", "kicked", "banned"]:
            return False
        return False
    except BadRequest as e:
        err_text = str(e).lower()
        # In Telegram broadcast channels, non-members raise PARTICIPANT_ID_INVALID or user not found
        if "participant_id_invalid" in err_text or "user not found" in err_text or "not a member" in err_text:
            return False
        logger.warning(f"BadRequest checking channel membership for user {user_id}: {e}. Ensure bot is channel admin.")
        return True
    except TelegramError as e:
        logger.warning(f"Error checking channel membership for user {user_id}: {e}. Failing open.")
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
    # Show admin button only for admins/owner
    if user_id and is_admin(user_id):
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

    # Target log destination: send to LOG_CHANNEL_ID if provided; otherwise fallback to OWNER_ID
    target_chat = LOG_CHANNEL_ID if LOG_CHANNEL_ID else (OWNER_ID if OWNER_ID and user.id != OWNER_ID else None)
    if target_chat:
        try:
            await context.bot.send_message(
                chat_id=target_chat,
                text=alert_text,
                parse_mode="HTML"
            )
            logger.info(f"Broadcasted new user alert to {target_chat} for user {user.id}")
        except Exception as e:
            logger.warning(f"Failed to send new user alert to {target_chat}: {e}")

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

# Stats command (admin only)
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ This command is restricted to bot administrators.")
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

def format_ig_links_html(accounts: Optional[List[str]]) -> str:
    """
    Formats Instagram usernames into clickable Instagram profile HTML links.
    Ensures Telegram does not convert them into internal Telegram username mentions.
    """
    if not accounts:
        return "❌ Not linked"
    links = []
    for a in accounts:
        clean = str(a).replace("@", "").strip().strip(".")
        if clean:
            links.append(f'<a href="https://www.instagram.com/{clean}/">@{clean}</a>')
    return "✅ Linked: " + ", ".join(links) if links else "❌ Not linked"

def generate_users_pdf(users: List[Dict[str, Any]]) -> bytes:
    """Generates a styled landscape PDF report listing all users."""
    import io
    import datetime
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        rightMargin=20,
        leftMargin=20,
        topMargin=25,
        bottomMargin=20
    )
    styles = getSampleStyleSheet()

    def safe(text):
        if not text:
            return "N/A"
        return "".join(c if ord(c) < 256 else "?" for c in str(text))

    elements = []
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0F172A')
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#64748B')
    )
    
    elements.append(Paragraph("<b>ReelGram — Registered Users Report</b>", title_style))
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"Generated at: {now_str} UTC &nbsp;|&nbsp; Total Users: <b>{len(users)}</b>", subtitle_style))
    elements.append(Spacer(1, 15))

    headers = ["#", "User ID", "Name", "Permanent Link", "Instagram", "Completed", "Failed"]
    table_data = [headers]

    cell_style = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1E293B')
    )

    for idx, u in enumerate(users, 1):
        uid = str(u.get("telegram_chat_id", ""))
        name = safe(u.get("first_name"))
        perm_link = f"tg://user?id={uid}"
        
        accs = u.get("linked_accounts") or []
        ig_text = ", ".join(f"@{safe(a)}" for a in accs) if accs else "Not linked"
        completed = str(u.get("completed_count", 0))
        failed = str(u.get("failed_count", 0))

        row = [
            Paragraph(str(idx), cell_style),
            Paragraph(uid, cell_style),
            Paragraph(name, cell_style),
            Paragraph(perm_link, cell_style),
            Paragraph(ig_text, cell_style),
            Paragraph(completed, cell_style),
            Paragraph(failed, cell_style),
        ]
        table_data.append(row)

    col_widths = [30, 95, 145, 185, 150, 75, 60]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (5, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]))

    elements.append(table)
    doc.build(elements)
    return buf.getvalue()

# Users command (admin only)
async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ This command is restricted to bot administrators.")
        return
    await send_all_users_report(update)

async def send_all_users_report(update: Update) -> None:
    """Generates and delivers a comprehensive user report as HTML message or PDF."""
    users = get_all_users_detailed()
    if not users:
        err_msg = "👥 <b>No registered users found in database.</b>"
        if update.message:
            await update.message.reply_text(err_msg, parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.message.reply_text(err_msg, parse_mode="HTML")
        return

    total = len(users)
    lines = [
        "👥 <b>ʀᴇᴇʟɢʀᴀᴍ — Registered Users Report</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"<b>Total Users:</b> <b>{total}</b>",
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for idx, u in enumerate(users, 1):
        uid = u.get("telegram_chat_id")
        name = u.get("first_name") or "Anonymous"
        perm_link = f"tg://user?id={uid}"
        accs = u.get("linked_accounts")
        ig_str = format_ig_links_html(accs)
        completed = u.get("completed_count", 0)
        failed = u.get("failed_count", 0)

        entry = (
            f"<b>{idx}. Name:</b> <a href=\"{perm_link}\">{html.escape(name)}</a>\n"
            f"   • <b>ID:</b> <code>{uid}</code>\n"
            f"   • <b>Permanent Link:</b> <a href=\"{perm_link}\">{perm_link}</a>\n"
            f"   • <b>Instagram:</b> {ig_str}\n"
            f"   • <b>Completed Reels:</b> <b>{completed}</b>\n"
            f"   • <b>Failed Reels:</b> <b>{failed}</b>\n"
        )
        lines.append(entry)

    full_text = "\n".join(lines)

    # If within 4000 characters, send as message. Otherwise, send as PDF.
    if len(full_text) <= 4000:
        if update.message:
            await update.message.reply_text(full_text, parse_mode="HTML", disable_web_page_preview=True)
        elif update.callback_query:
            await update.callback_query.message.reply_text(full_text, parse_mode="HTML", disable_web_page_preview=True)
    else:
        try:
            import io
            pdf_bytes = generate_users_pdf(users)
            caption = (
                f"📄 <b>ʀᴇᴇʟɢʀᴀᴍ — Users Report (PDF)</b>\n\n"
                f"• <b>Total Users:</b> <b>{total}</b>\n"
                f"<i>(Delivered as PDF because the user list exceeds Telegram's 4,096 character message limit)</i>"
            )
            if update.message:
                await update.message.reply_document(
                    document=io.BytesIO(pdf_bytes),
                    filename="reelgram_users.pdf",
                    caption=caption,
                    parse_mode="HTML"
                )
            elif update.callback_query:
                await update.callback_query.message.reply_document(
                    document=io.BytesIO(pdf_bytes),
                    filename="reelgram_users.pdf",
                    caption=caption,
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Error generating PDF report: {e}", exc_info=True)
            # Fallback in chunks
            chunk = ""
            for item in lines:
                if len(chunk) + len(item) + 2 > 3800:
                    await update.effective_chat.send_message(chunk, parse_mode="HTML", disable_web_page_preview=True)
                    chunk = item + "\n"
                else:
                    chunk += item + "\n"
            if chunk:
                await update.effective_chat.send_message(chunk, parse_mode="HTML", disable_web_page_preview=True)

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
            
            # Format Instagram links properly as Instagram URLs, NOT Telegram mentions!
            accs = u.get("linked_accounts")
            if not accs and u.get("linked_instagram"):
                raw_ig = str(u.get("linked_instagram"))
                accs = [a.replace("@", "").strip() for a in raw_ig.split(",") if a.strip()]
            
            ig_str = format_ig_links_html(accs)
            reels = u.get("reels_received", 0)
            seen = u.get("last_seen")
            seen_str = seen.strftime("%b %d, %H:%M") if hasattr(seen, "strftime") else "Recently"
            
            text += f"<b>{idx}. {html.escape(name)}</b> ({uname})\n"
            text += f"   • Chat ID: <code>{tg_id}</code>\n"
            text += f"   • Instagram: {ig_str}\n"
            text += f"   • Reels Received: <b>{reels}</b> | Seen: {seen_str}\n\n"

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh List", callback_data="admin_recent_users"),
            InlineKeyboardButton("📄 Full Report (PDF/Msg)", callback_data="admin_full_users")
        ],
        [
            InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats"),
            InlineKeyboardButton("🔙 Back to Admin", callback_data="show_admin")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)
    elif update.callback_query:
        try:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass

# Broadcast command (owner only)
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ This command is restricted to bot administrators.")
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
        code, status = create_pending_registration(instagram_username, chat_id)
        
        if status == "already_linked_to_you":
            text = (
                f"ℹ️ <b>Already Linked</b>\n\n"
                f"The Instagram account <a href=\"https://www.instagram.com/{instagram_username}\">@{instagram_username}</a> is already linked and verified to this Telegram chat!"
            )
            keyboard = [
                [InlineKeyboardButton("📱 Check Status", callback_data="show_status")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]
            ]
            if update.message:
                await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return

        if status == "already_linked_by_other":
            text = (
                f"⛔ <b>Account Already Linked</b>\n\n"
                f"The Instagram account <a href=\"https://www.instagram.com/{instagram_username}\">@{instagram_username}</a> is already linked to another Telegram user.\n\n"
                f"🔒 <i>For security, an Instagram account can only be connected to one Telegram chat at a time. If this is your account, please unlink it from your other chat first.</i>"
            )
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]
            if update.message:
                await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return

        if status == "limit_reached":
            verified = get_verified_registrations(chat_id)
            accounts_list = "\n".join([f"• <a href=\"https://instagram.com/{r['instagram_username']}\">@{r['instagram_username']}</a>" for r in verified])
            text = (
                f"⚠️ <b>Account Limit Reached (2/2)</b>\n\n"
                f"You have already linked the maximum of <b>2 Instagram accounts</b> to this chat:\n"
                f"{accounts_list}\n\n"
                f"Please use <code>/unlink</code> to remove an account before adding a new one."
            )
            keyboard = [
                [InlineKeyboardButton("❌ Manage / Unlink", callback_data="show_unlink_menu")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]
            ]
            if update.message:
                await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return
        
        # Trigger fast Instagram polling so verification happens within seconds
        try:
            from instagram.monitor import notify_registration_started
            notify_registration_started()
        except Exception as e:
            logger.debug(f"Could not notify monitor for fast registration: {e}")

        # Check which slot this will occupy
        verified_count = len(get_verified_registrations(chat_id))
        slot_text = f"Slot {verified_count + 1} of 2"

        ig_profile = f'<a href="https://www.instagram.com/{instagram_username}">@{instagram_username}</a>'
        ig_bot = f'<a href="https://www.instagram.com/{INSTAGRAM_USERNAME}">@{INSTAGRAM_USERNAME}</a>' if INSTAGRAM_USERNAME else "@our_bot_account"
        text = (
            f"🔑 <b>Verification Code:</b> <code>verify {code}</code>\n\n"
            f"Linking: {ig_profile} ({slot_text})\n\n"
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
        regs = get_registrations_by_telegram(chat_id)
        verified_regs = [r for r in regs if r.get("verified")]
        pending_regs = [r for r in regs if not r.get("verified")]
        keyboard = []

        if verified_regs:
            lines = []
            for idx, r in enumerate(verified_regs, 1):
                u = r.get("instagram_username")
                lines.append(f"• <b>Slot {idx}:</b> <a href=\"https://www.instagram.com/{u}\">@{u}</a> (Verified ✅)")
            
            accounts_summary = "\n".join(lines)
            slot_count = len(verified_regs)
            
            text = (
                f"📱 <b>Linked Instagram Accounts ({slot_count}/2)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{accounts_summary}\n\n"
            )
            
            if pending_regs:
                p = pending_regs[0]
                text += (
                    f"⏳ <b>Pending Verification:</b>\n"
                    f"• Account: <a href=\"https://www.instagram.com/{p.get('instagram_username')}\">@{p.get('instagram_username')}</a>\n"
                    f"• Code: <code>verify {p.get('verification_code')}</code>\n\n"
                )

            if slot_count < 2:
                text += "💡 <i>You can link a 2nd Instagram account anytime! Send <code>/register &lt;username&gt;</code> or click below.</i>"
                keyboard.append([InlineKeyboardButton("➕ Link 2nd Account", callback_data="show_link_info")])
            else:
                text += "⚡ <i>Maximum 2 accounts connected! Reels sent from either Instagram account will be delivered straight to this chat.</i>"

            keyboard.append([InlineKeyboardButton("❌ Manage / Unlink Accounts", callback_data="show_unlink_menu")])
        elif pending_regs:
            p = pending_regs[0]
            u = p.get("instagram_username")
            code = p.get("verification_code")
            text = (
                f"⚠️ <b>Verification Pending</b>\n\n"
                f"• <b>Instagram:</b> <a href=\"https://www.instagram.com/{u}\">@{u}</a>\n"
                f"• <b>Verification Code:</b> <code>verify {code}</code>\n\n"
                f"Send <code>verify {code}</code> to the Instagram bot to link."
            )
            keyboard.append([InlineKeyboardButton("🔄 Verify/Retry Link", callback_data="show_link_info")])
        else:
            text = (
                "❌ <b>No Instagram account linked to this chat.</b>\n\n"
                "You can link up to <b>2 Instagram accounts</b> to automatically receive Reels here.\n\n"
                "Click the button below to link your first account:"
            )
            keyboard.append([InlineKeyboardButton("🔑 Link Account", callback_data="show_link_info")])
            
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")])
        
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return
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
    await execute_unlink_menu(update, chat_id)

async def execute_unlink_menu(update: Update, chat_id: str):
    try:
        verified_regs = get_verified_registrations(chat_id)
        if not verified_regs:
            text = "❌ <b>No Instagram accounts are linked to this chat.</b>"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]
        elif len(verified_regs) == 1:
            u = verified_regs[0].get("instagram_username")
            text = f"⚠️ <b>Are you sure you want to unlink <a href=\"https://instagram.com/{u}\">@{u}</a>?</b>"
            keyboard = [
                [InlineKeyboardButton(f"✅ Yes, Unlink @{u}", callback_data=f"do_unlink:{u}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="show_status")]
            ]
        else:
            text = "⚙️ <b>Manage Linked Accounts</b>\n\nChoose an account to unlink, or unlink both:"
            keyboard = []
            for r in verified_regs:
                u = r.get("instagram_username")
                keyboard.append([InlineKeyboardButton(f"❌ Unlink @{u}", callback_data=f"do_unlink:{u}")])
            keyboard.append([InlineKeyboardButton("🗑️ Unlink Both Accounts", callback_data="do_unlink:all")])
            keyboard.append([InlineKeyboardButton("🔙 Back to Status", callback_data="show_status")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")

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
            "Or send your username directly in this chat.\n\n"
            "💡 <i>You can link up to <b>2 Instagram accounts</b> to this Telegram chat!</i>"
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
        if not is_admin(user_id):
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
        if not is_admin(user_id):
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        await send_stats_message(update)

    elif data == "refresh_stats":
        if not is_admin(user_id):
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        await send_stats_message(update)
        await query.answer("✅ Stats refreshed!")

    elif data == "admin_recent_users":
        if not is_admin(user_id):
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        await send_recent_users_message(update)

    elif data == "admin_full_users":
        if not is_admin(user_id):
            await query.answer("⛔ Unauthorized.", show_alert=True)
            return
        await query.answer("⏳ Generating full users report...")
        await send_all_users_report(update)

    elif data == "admin_broadcast":
        if not is_admin(user_id):
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
        
    elif data == "show_unlink_menu":
        await execute_unlink_menu(update, chat_id)
        
    elif data == "confirm_unlink":
        await execute_unlink_menu(update, chat_id)
        
    elif data.startswith("do_unlink"):
        target = data.split(":", 1)[1] if ":" in data else "all"
        if target == "all":
            unlink_user_by_telegram(chat_id)
            await query.message.edit_text(
                "✅ <b>Successfully unlinked all Instagram accounts from this chat.</b>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]]),
                parse_mode="HTML"
            )
        else:
            unlink_user_by_telegram(chat_id, instagram_username=target)
            await query.message.edit_text(
                f"✅ <b>Successfully unlinked @{target} from this chat.</b>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📱 Check Status", callback_data="show_status")],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="show_start")]
                ]),
                parse_mode="HTML"
            )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat or not update.message:
        return
    user_id = update.effective_user.id
    chat_id = str(update.effective_chat.id)

    # Check if admin is in broadcast mode
    if chat_id in _broadcast_mode and is_admin(user_id):
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
    
    if chat_id in _broadcast_mode and is_admin(user_id):
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
