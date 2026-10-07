import os
import json
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------- CONFIG ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "")
FOOTBALL_API_URL = "https://v3.football.api-sports.io/fixtures"
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
BOT_USERNAME = "promo_566bot"
BOT_NAME = "Promo 566"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- PERSISTENCE ----------
DATA_FILE = Path("data.json")

def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {
        "checkin": {},
        "points": {},
        "streak": {},
        "referrals": {},
        "referred_by": {},
        "redeemed_promos": {},
        "giveaway_entries": [],
        "giveaway_active": False,
        "flash_promo": None,   # {"code": "...", "points": int, "expires": iso}
    }

def save_data():
    DATA_FILE.write_text(json.dumps(DB, indent=2))

DB = load_data()

# ---------- PROMO CODES ----------
# Tiered promos: welcome / daily / streak / weekend / VIP / flash
PROMOS = {
    # --- Welcome tier ---
    "PROMO566":   {"points": 30,  "uses_left": 9999, "expires": None, "label": "Welcome Bonus",     "tier": "welcome"},
    "HELLO566":   {"points": 15,  "uses_left": 9999, "expires": None, "label": "First Visit Bonus", "tier": "welcome"},

    # --- Football tier ---
    "GOAL566":    {"points": 20,  "uses_left": 999,  "expires": None, "label": "Football Fan Bonus", "tier": "football"},
    "MATCHDAY":   {"points": 25,  "uses_left": 999,  "expires": None, "label": "Match Day Promo",    "tier": "football"},

    # --- Streak tier ---
    "STREAK7":    {"points": 70,  "uses_left": 500,  "expires": None, "label": "7-Day Streak Reward", "tier": "streak"},
    "LOYAL566":   {"points": 50,  "uses_left": 500,  "expires": None, "label": "Loyalty Reward",      "tier": "streak"},

    # --- Weekend tier ---
    "WEEKEND566": {"points": 40,  "uses_left": 300,  "expires": None, "label": "Weekend Special",     "tier": "weekend"},

    # --- VIP tier ---
    "VIP566":     {"points": 150, "uses_left": 100,  "expires": None, "label": "VIP Community Promo", "tier": "vip"},
}

DAILY_ROTATION = ["PROMO566", "GOAL566", "STREAK7", "WEEKEND566", "MATCHDAY", "LOYAL566", "VIP566"]

def get_daily_promo():
    idx = datetime.utcnow().toordinal() % len(DAILY_ROTATION)
    code = DAILY_ROTATION[idx]
    return code, PROMOS[code]


# ---------- HELPERS ----------
def get_points(uid):
    return DB["points"].get(str(uid), 0)

def add_points(uid, amount):
    uid = str(uid)
    DB["points"][uid] = DB["points"].get(uid, 0) + amount
    save_data()

def is_admin(uid):
    return uid in ADMIN_IDS


async def _reply(update: Update, text):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    # Referral handling
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg.replace("ref_", ""))
                if referrer_id != uid and str(uid) not in DB["referred_by"]:
                    DB["referred_by"][str(uid)] = referrer_id
                    DB["referrals"].setdefault(str(referrer_id), []).append(uid)
                    add_points(referrer_id, 20)
                    add_points(uid, 10)
                    save_data()
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            "🎉 Someone joined via your link! +20 points",
                        )
                    except Exception:
                        pass
            except Exception:
                pass

    keyboard = [
        [InlineKeyboardButton("🔥 Today's Promo", callback_data="promo"),
         InlineKeyboardButton("🎟️ Redeem Code", callback_data="redeem_hint")],
        [InlineKeyboardButton("⚽ Football", callback_data="football"),
         InlineKeyboardButton("🔴 Live", callback_data="live")],
        [InlineKeyboardButton("🎁 Giveaway", callback_data="giveaway_join"),
         InlineKeyboardButton("✅ Check-in", callback_data="checkin")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
         InlineKeyboardButton("👥 My Referrals", callback_data="referrals")],
        [InlineKeyboardButton("💎 My Points", callback_data="points"),
         InlineKeyboardButton("📖 Help", callback_data="help")],
    ]

    text = (
        f"👋 Hello <b>{user.first_name}</b>!\n\n"
        f"Welcome to <b>{BOT_NAME}</b> 🔥🎁⚽\n\n"
        "What I can do:\n"
        "• 🔥 <b>Promo Codes</b> — Redeem for bonus points\n"
        "• ⚽ <b>Football</b> — Live scores & fixtures\n"
        "• 🎁 <b>Giveaway</b> — Join community draws\n"
        "• ✅ <b>Check-in</b> — Earn points daily (streak bonus!)\n"
        "• 👥 <b>Referrals</b> — Invite & earn\n"
        "• 🏆 <b>Leaderboard</b> — See top earners\n\n"
        f"💎 Your points: <b>{get_points(uid)}</b>"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ---------- /help ----------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code, promo = get_daily_promo()
    text = (
        "📖 <b>Commands</b>\n\n"
        "/start – Main menu\n"
        "/football – Today's fixtures\n"
        "/live – Live matches\n"
        "/giveaway – Join giveaway\n"
        "/checkin – Daily reward\n"
        "/points – Your balance\n"
        "/promo – Today's featured promo\n"
        "/redeem CODE – Redeem a code\n"
        "/flash – View current flash promo\n"
        "/invite – Your referral link\n"
        "/referrals – Invite count\n"
        "/leaderboard – Top 10 users\n"
        "/help – This menu\n\n"
        f"🔥 <b>Today's hint:</b> {promo['label']}"
    )
    await _reply(update, text)


# ---------- FOOTBALL ----------
def fetch_fixtures(live_only=False):
    if not FOOTBALL_API_KEY:
        return None
    headers = {"x-apisports-key": FOOTBALL_API_KEY}
    params = {"live": "all"} if live_only else {"date": datetime.utcnow().strftime("%Y-%m-%d")}
    try:
        r = requests.get(FOOTBALL_API_URL, headers=headers, params=params, timeout=10)
        return r.json().get("response", [])
    except Exception as e:
        logger.error(f"Football API error: {e}")
        return None


def format_fixtures(fixtures, live_only=False):
    if fixtures is None:
        return "⚠️ Football data temporarily unavailable."
    if not fixtures:
        return "📭 No matches right now."
    lines = ["⚽ <b>Live Matches</b>\n" if live_only else "⚽ <b>Today's Fixtures</b>\n"]
    for f in fixtures[:10]:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        gh, ga = f["goals"]["home"], f["goals"]["away"]
        status = f["fixture"]["status"]["short"]
        league = f["league"]["name"]
        score = f"{gh or 0} - {ga or 0}" if (live_only or status in ("1H","2H","HT","ET","P")) else "vs"
        lines.append(f"🏆 {league}\n   {home}  <b>{score}</b>  {away}\n")
    return "\n".join(lines)


async def football(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    await msg.reply_text("🔎 Fetching today's fixtures...")
    fixtures = fetch_fixtures(False)
    await msg.reply_text(format_fixtures(fixtures), parse_mode="HTML", disable_web_page_preview=True)


async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    await msg.reply_text("🔎 Fetching live matches...")
    fixtures = fetch_fixtures(True)
    await msg.reply_text(format_fixtures(fixtures, True), parse_mode="HTML", disable_web_page_preview=True)


# ---------- GIVEAWAY ----------
async def giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await join_giveaway(update, context)


async def join_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not DB["giveaway_active"]:
        msg = "❌ No giveaway running right now."
    elif uid in DB["giveaway_entries"]:
        msg = "✅ You're already in! Good luck 🍀"
    else:
        DB["giveaway_entries"].append(uid)
        save_data()
        msg = f"🎉 You joined! Total entries: {len(DB['giveaway_entries'])}"
    await _reply(update, msg)


async def start_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorized.")
    DB["giveaway_active"] = True
    DB["giveaway_entries"] = []
    save_data()
    await update.message.reply_text("🎉 New giveaway started! Users can /giveaway to join.")


async def end_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorized.")
    if not DB["giveaway_entries"]:
        DB["giveaway_active"] = False
        save_data()
        return await update.message.reply_text("❌ No participants.")
    winner_id = random.choice(DB["giveaway_entries"])
    try:
        w = await context.bot.get_chat(winner_id)
        name = w.first_name
    except Exception:
        name = f"User {winner_id}"
    await update.message.reply_text(
        f"🏆 <b>Winner:</b> {name}! 🎉\nEntries: {len(DB['giveaway_entries'])}",
        parse_mode="HTML",
    )
    DB["giveaway_active"] = False
    DB["giveaway_entries"] = []
    save_data()


# ---------- CHECK-IN ----------
async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    now = datetime.utcnow()
    last = DB["checkin"].get(uid)

    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt < timedelta(hours=24):
            remain = timedelta(hours=24) - (now - last_dt)
            h, r = divmod(int(remain.total_seconds()), 3600)
            m = r // 60
            return await _reply(update, f"⏳ Already checked in! Come back in <b>{h}h {m}m</b>.")

        if now - last_dt < timedelta(hours=48):
            DB["streak"][uid] = DB["streak"].get(uid, 0) + 1
        else:
            DB["streak"][uid] = 1
    else:
        DB["streak"][uid] = 1

    streak = DB["streak"][uid]
    base = random.randint(5, 15)
    streak_bonus = min(streak, 7) * 2
    total = base + streak_bonus

    DB["checkin"][uid] = now.isoformat()
    add_points(uid, total)

    msg = (
        f"✅ <b>Check-in successful!</b>\n\n"
        f"Base: <b>{base}</b> pts\n"
        f"🔥 Streak (day {streak}): <b>+{streak_bonus}</b> pts\n"
        f"💰 Earned: <b>{total}</b> pts\n"
        f"💎 Total: <b>{get_points(uid)}</b>"
    )
    await _reply(update, msg)


# ---------- POINTS ----------
async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    streak = DB["streak"].get(str(uid), 0)
    refs = len(DB["referrals"].get(str(uid), []))
    msg = (
        f"💎 <b>Your Stats</b>\n\n"
        f"Points: <b>{get_points(uid)}</b>\n"
        f"🔥 Streak: <b>{streak} day(s)</b>\n"
        f"👥 Referrals: <b>{refs}</b>"
    )
    await _reply(update, msg)


# ---------- PROMO ----------
async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code, info = get_daily_promo()
    text = (
        f"🔥 <b>Today's Featured Promo</b>\n\n"
        f"🏷️ Label: <b>{info['label']}</b>\n"
        f"🎁 Reward: <b>{info['points']} points</b>\n"
        f"⏳ Uses left: <b>{info['uses_left']}</b>\n\n"
        f"💡 Redeem with:\n<code>/redeem {code}</code>"
    )
    await _reply(update, text)


async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if not context.args:
        return await _reply(update, "❌ Usage: <code>/redeem CODE</code>")
    code = context.args[0].upper().strip()

    # Check flash first
    flash = DB.get("flash_promo")
    if flash and flash["code"] == code:
        if datetime.utcnow() > datetime.fromisoformat(flash["expires"]):
            return await _reply(update, "❌ Flash promo has expired.")
        redeemed = DB["redeemed_promos"].setdefault(uid, [])
        if code in redeemed:
            return await _reply(update, "⚠️ You already redeemed this flash code.")
        redeemed.append(code)
        add_points(uid, flash["points"])
        save_data()
        return await _reply(update,
            f"⚡ <b>Flash Promo Redeemed!</b>\n\n"
            f"Code: <code>{code}</code>\n"
            f"Reward: <b>+{flash['points']} points</b>\n"
            f"💎 Total: <b>{get_points(uid)}</b>")

    if code not in PROMOS:
        return await _reply(update, "❌ Invalid promo code.")
    p = PROMOS[code]
    if p["uses_left"] <= 0:
        return await _reply(update, "❌ This promo has been fully used.")
    redeemed = DB["redeemed_promos"].setdefault(uid, [])
    if code in redeemed:
        return await _reply(update, "⚠️ You already redeemed this code.")
    if p.get("expires") and datetime.utcnow() > datetime.fromisoformat(p["expires"]):
        return await _reply(update, "❌ This promo has expired.")

    p["uses_left"] -= 1
    redeemed.append(code)
    add_points(uid, p["points"])
    save_data()

    await _reply(update,
        f"🎉 <b>Promo Redeemed!</b>\n\n"
        f"Code: <code>{code}</code>\n"
        f"Label: <b>{p['label']}</b>\n"
        f"Reward: <b>+{p['points']} points</b>\n"
        f"💎 Total: <b>{get_points(uid)}</b>")


# ---------- FLASH PROMO ----------
async def flash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flash_data = DB.get("flash_promo")
    if not flash_data:
        return await _reply(update,
            "⚡ <b>No flash promo active.</b>\n\nFlash promos drop randomly — stay tuned!")
    exp = datetime.fromisoformat(flash_data["expires"])
    if datetime.utcnow() > exp:
        DB["flash_promo"] = None
        save_data()
        return await _reply(update, "⚡ Flash promo has just expired.")
    remain = exp - datetime.utcnow()
    mins = int(remain.total_seconds() // 60)
    text = (
        f"⚡ <b>FLASH PROMO ACTIVE!</b>\n\n"
        f"🎁 Reward: <b>{flash_data['points']} points</b>\n"
        f"⏰ Expires in: <b>{mins} min</b>\n\n"
        f"💡 Redeem fast:\n<code>/redeem {flash_data['code']}</code>"
    )
    await _reply(update, text)


async def start_flash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /startflash CODE POINTS MINUTES"""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorized.")
    if len(context.args) < 3:
        return await update.message.reply_text("Usage: /startflash CODE POINTS MINUTES")
    try:
        code = context.args[0].upper()
        pts = int(context.args[1])
        mins = int(context.args[2])
    except Exception:
        return await update.message.reply_text("❌ Invalid arguments.")

    expires = (datetime.utcnow() + timedelta(minutes=mins)).isoformat()
    DB["flash_promo"] = {"code": code, "points": pts, "expires": expires}
    save_data()

    # Broadcast flash to all users
    users = set(list(DB["points"].keys()) + list(DB["checkin"].keys()))
    sent = 0
    for uid in users:
        try:
            await context.bot.send_message(
                int(uid),
                f"⚡ <b>FLASH PROMO DROPPED!</b>\n\n"
                f"Code: <code>{code}</code>\n"
                f"Reward: <b>{pts} points</b>\n"
                f"⏰ Expires in <b>{mins} minutes</b>!\n\n"
                f"Redeem now: /redeem {code}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"⚡ Flash promo live! Sent to {sent} users.")


# ---------- REFERRALS ----------
async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    text = (
        f"👥 <b>Invite Friends — Earn 20 points each!</b>\n\n"
        f"Your personal link:\n"
        f"<code>{link}</code>\n\n"
        f"• You get <b>+20 pts</b> per new user\n"
        f"• They get <b>+10 pts</b> welcome bonus"
    )
    await _reply(update, text)


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    count = len(DB["referrals"].get(uid, []))
    msg = (
        f"👥 <b>Your Referrals</b>\n\n"
        f"Total invited: <b>{count}</b>\n"
        f"Points earned: <b>{count * 20}</b>"
    )
    await _reply(update, msg)


# ---------- LEADERBOARD ----------
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pts = DB["points"]
    top = sorted(pts.items(), key=lambda x: x[1], reverse=True)[:10]
    if not top:
        return await _reply(update, "🏆 No users yet. Be the first!")

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Top 10 Leaderboard</b>\n"]
    for i, (uid, score) in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i+1}."
        try:
            u = await context.bot.get_chat(int(uid))
            name = u.first_name or u.username or f"User {uid}"
        except Exception:
            name = f"User {uid}"
        lines.append(f"{prefix} {name} — <b>{score}</b> 💎")
    await _reply(update, "\n".join(lines))


# ---------- BROADCAST ----------
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Not authorized.")
    if not context.args:
        return await update.message.reply_text("Usage: /broadcast Your message")
    msg = " ".join(context.args)
    users = set(list(DB["points"].keys()) + list(DB["checkin"].keys()))
    sent, failed = 0, 0
    for uid in users:
        try:
            await context.bot.send_message(int(uid), f"📢 {msg}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ Sent: {sent} | ❌ Failed: {failed}")


# ---------- ROUTER ----------
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "football":
        await update.callback_query.answer()
        fixtures = fetch_fixtures(False)
        await update.callback_query.message.reply_text(
            format_fixtures(fixtures), parse_mode="HTML", disable_web_page_preview=True)
    elif data == "live":
        await update.callback_query.answer()
        fixtures = fetch_fixtures(True)
        await update.callback_query.message.reply_text(
            format_fixtures(fixtures, True), parse_mode="HTML", disable_web_page_preview=True)
    elif data == "giveaway_join":
        await join_giveaway(update, context)
    elif data == "checkin":
        await checkin(update, context)
    elif data == "promo":
        await promo(update, context)
    elif data == "redeem_hint":
        await _reply(update, "💡 Send <code>/redeem CODE</code>\n\nExample: <code>/redeem PROMO566</code>")
    elif data == "referrals":
        await referrals(update, context)
    elif data == "points":
        await points(update, context)
    elif data == "leaderboard":
        await leaderboard(update, context)
    elif data == "help":
        await help_command(update, context)


# ---------- MAIN ----------
def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("football", football))
    app.add_handler(CommandHandler("live", live))
    app.add_handler(CommandHandler("giveaway", giveaway))
    app.add_handler(CommandHandler("startgiveaway", start_giveaway))
    app.add_handler(CommandHandler("endgiveaway", end_giveaway))
    app.add_handler(CommandHandler("checkin", checkin))
    app.add_handler(CommandHandler("points", points))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("flash", flash))
    app.add_handler(CommandHandler("startflash", start_flash))
    app.add_handler(CommandHandler("invite", invite))
    app.add_handler(CommandHandler("referrals", referrals))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(button_router))

    logger.info(f"🤖 {BOT_NAME} is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
