import os
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import pytz
import telebot
from supabase import create_client


# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GROUP_ID = -1004332813760
LOGS_TOPIC_ID = 64
GENERAL_TOPIC_ID = 1
ADMIN_ID = 8103251058
TIMEZONE = pytz.timezone("Africa/Addis_Ababa")
DAY_RESET_HOUR = 6
CHALLENGE_START = datetime(2026, 6, 29, 6, 0, 0, tzinfo=pytz.timezone("Africa/Addis_Ababa"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # your Vercel URL

logging.basicConfig(level=logging.INFO)

# ── Init ──────────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)

# conversation state stored in memory per user
user_states = {}
WAITING_FOR_MEMBER_ID = "waiting_for_member_id"
WAITING_FOR_LOG = "waiting_for_log"

# ── Helpers ───────────────────────────────────────────────────────────────────

def current_day_str() -> str:
    now = datetime.now(TIMEZONE)
    if now.hour < DAY_RESET_HOUR:
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def challenge_day_number() -> int:
    now = datetime.now(TIMEZONE)
    if now < CHALLENGE_START:
        return 0
    delta = (now - CHALLENGE_START).days + 1
    return max(1, min(delta, 90))


def get_user(user_id: str):
    res = supabase.table("members").select("*").eq("user_id", user_id).execute()
    if res.data:
        return res.data[0]
    return None


def create_user(user_id: str, name: str):
    supabase.table("members").insert({
        "user_id": user_id,
        "name": name,
        "member_id": "",
        "streak": 0,
        "last_log": None,
        "total_logs": 0,
    }).execute()


def update_user(user_id: str, data: dict):
    supabase.table("members").update(data).eq("user_id", user_id).execute()


def build_leaderboard_text() -> str:
    res = supabase.table("members").select("*").order("streak", desc=True).execute()
    if not res.data:
        return "No logs yet! Be the first with /log 🔥"

    medals = ["🥇", "🥈", "🥉"]
    day = challenge_day_number()
    day_text = f"Day {day}/90" if day > 0 else "Challenge starts June 29"
    lines = [f"🏆 *LockIn 90 — Leaderboard*\n📅 {day_text}\n"]

    for i, profile in enumerate(res.data):
        name = profile.get("name") or f"Member {i+1}"
        member_id = profile.get("member_id") or "—"
        streak_count = profile.get("streak", 0)
        medal = medals[i] if i < 3 else f"{i+1}."
        logged_today = "✅" if profile.get("last_log") == current_day_str() else "💤"
        lines.append(f"{medal} {name} (`{member_id}`) — *{streak_count} days* {logged_today}")

    lines.append("\n✅ = logged today  💤 = not yet")
    return "\n".join(lines)


# ── Handlers ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def handle_start(message):
    user_id = str(message.from_user.id)
    name = message.from_user.first_name
    profile = get_user(user_id)

    if profile and profile.get("member_id"):
        day = challenge_day_number()
        day_text = f"We're on *Day {day}/90*!" if day > 0 else "The challenge starts *tomorrow, June 29*! 🚀"
        bot.send_message(message.chat.id,
            f"👋 Welcome back, {name}!\n\n{day_text}\n\n"
            "📋 *Commands:*\n"
            "/log — Submit your daily log\n"
            "/streak — See your current streak\n"
            "/leaderboard — See everyone's streaks",
            parse_mode="Markdown")
        return

    if not profile:
        create_user(user_id, name)

    user_states[user_id] = WAITING_FOR_MEMBER_ID
    bot.send_message(message.chat.id,
        f"🌟 *Welcome to Summer LockIn 90, {name}!*\n\n"
        "Before we begin, what is your *member ID*?\n\n"
        "_(It looks like_ `LU90-001` _— check with your group admin if unsure)_",
        parse_mode="Markdown")


@bot.message_handler(commands=["log"])
def handle_log(message):
    user_id = str(message.from_user.id)
    profile = get_user(user_id)

    if not profile or not profile.get("member_id"):
        bot.send_message(message.chat.id, "⚠️ You need to register first! Send /start to set up your member ID.")
        return

    day = challenge_day_number()
    if day == 0:
        bot.send_message(message.chat.id,
            "⏳ The challenge hasn't started yet!\n\nCome back on *June 29* to submit your first log. 🚀",
            parse_mode="Markdown")
        return

    if profile.get("last_log") == current_day_str():
        bot.send_message(message.chat.id,
            f"✅ You already logged today!\n"
            f"🔥 Current streak: *{profile['streak']} days*\n\nCome back tomorrow!",
            parse_mode="Markdown")
        return

    user_states[user_id] = WAITING_FOR_LOG
    member_id = profile["member_id"]
    bot.send_message(message.chat.id,
        f"📋 *Daily Log — Day {day}/90*\n\n"
        f"Send your log below:\n\n"
        f"`ID: {member_id}`\n"
        f"`Day: {day}/90`\n"
        "`Plan:`\n`- Task 1`\n`- Task 2`\n"
        "`Progress:`\n`- What you actually did`\n\n"
        "_Send /cancel to stop._",
        parse_mode="Markdown")


@bot.message_handler(commands=["streak"])
def handle_streak(message):
    user_id = str(message.from_user.id)
    name = message.from_user.first_name
    profile = get_user(user_id)

    if not profile:
        bot.send_message(message.chat.id, "⚠️ You're not registered yet! Send /start first.")
        return

    logged_today = profile.get("last_log") == current_day_str()
    status = "✅ Logged today!" if logged_today else "⚠️ Not logged yet today"

    bot.send_message(message.chat.id,
        f"📊 *Your Stats, {name}*\n\n"
        f"🪪 Member ID: `{profile.get('member_id') or 'Not set'}`\n"
        f"🔥 Current streak: *{profile.get('streak', 0)} days*\n"
        f"📅 Total logs: *{profile.get('total_logs', 0)} days*\n"
        f"🗓 Last log: *{profile.get('last_log') or 'Never'}*\n"
        f"Today: {status}",
        parse_mode="Markdown")


@bot.message_handler(commands=["leaderboard"])
def handle_leaderboard(message):
    bot.send_message(message.chat.id, build_leaderboard_text(), parse_mode="Markdown")


@bot.message_handler(commands=["cancel"])
def handle_cancel(message):
    user_id = str(message.from_user.id)
    user_states.pop(user_id, None)
    bot.send_message(message.chat.id, "Cancelled. Come back when you're ready! 💙")


@bot.message_handler(commands=["testlog"])
def handle_testlog(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⚠️ Admin only.")
        return

    try:
        bot.send_message(GROUP_ID,
            "📋 *Daily Log — Day 1/90* _(TEST)_\n"
            "👤 Ruhama (`LU90-001`)\n🔥 Streak: 1 day\n\n"
            "ID: LU90-001\nDay: 1/90\nPlan:\n- Read Quran\n- Study Python\n"
            "Progress:\n- Done all ✅",
            message_thread_id=LOGS_TOPIC_ID, parse_mode="Markdown")
        bot.send_message(message.chat.id, "✅ Test log posted to Daily Logs!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Failed: {e}")

    try:
        bot.send_message(GROUP_ID,
            build_leaderboard_text() + "\n\n_(TEST)_",
            parse_mode="Markdown")
        bot.send_message(message.chat.id, "✅ Test leaderboard posted to General!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Leaderboard failed: {e}")


@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = str(message.from_user.id)
    name = message.from_user.first_name
    state = user_states.get(user_id)

    if state == WAITING_FOR_MEMBER_ID:
        member_id = message.text.strip().upper()
        if not member_id.startswith("LU90-"):
            bot.send_message(message.chat.id,
                "⚠️ Your ID should look like `LU90-001`. Try again:",
                parse_mode="Markdown")
            return

        update_user(user_id, {"name": name, "member_id": member_id})
        user_states.pop(user_id, None)

        day = challenge_day_number()
        day_text = f"We're on *Day {day}/90*!" if day > 0 else "The challenge starts *tomorrow, June 29*! 🚀"
        bot.send_message(message.chat.id,
            f"✅ *You're registered, {name}!*\n"
            f"🪪 Member ID: `{member_id}`\n\n{day_text}\n\n"
            "📋 *Commands:*\n"
            "/log — Submit your daily log\n"
            "/streak — See your current streak\n"
            "/leaderboard — See everyone's streaks\n\n"
            "Show up every day. Build the habit. 🔥",
            parse_mode="Markdown")

    elif state == WAITING_FOR_LOG:
        log_text = message.text
        if "ID:" not in log_text or ("Plan:" not in log_text and "Progress:" not in log_text):
            bot.send_message(message.chat.id,
                "⚠️ Your log needs *ID:*, *Plan:*, and *Progress:* sections.\n\nTry again or send /cancel.",
                parse_mode="Markdown")
            return

        profile = get_user(user_id)
        new_streak = profile.get("streak", 0) + 1
        update_user(user_id, {
            "streak": new_streak,
            "last_log": current_day_str(),
            "total_logs": profile.get("total_logs", 0) + 1,
            "name": name,
        })
        user_states.pop(user_id, None)

        milestone = ""
        if new_streak == 7:
            milestone = "\n\n🏅 *One week streak! Incredible!*"
        elif new_streak == 30:
            milestone = "\n\n🏆 *30 days! You're unstoppable!*"
        elif new_streak == 90:
            milestone = "\n\n👑 *90 DAYS! YOU DID IT! LEGEND!*"

        bot.send_message(message.chat.id,
            f"🔥 *Logged, {name}!*\n\n"
            f"⚡ Streak: *{new_streak} day{'s' if new_streak != 1 else ''}*{milestone}\n\n"
            "Your log has been posted to the group. Keep showing up! 💪",
            parse_mode="Markdown")

        day = challenge_day_number()
        try:
            bot.send_message(GROUP_ID,
                f"📋 *Daily Log — Day {day}/90*\n"
                f"👤 {name} (`{profile['member_id']}`)\n"
                f"🔥 Streak: {new_streak} day{'s' if new_streak != 1 else ''}\n\n{log_text}",
                message_thread_id=LOGS_TOPIC_ID, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Failed to post log: {e}")


# ── Webhook & cron endpoints ──────────────────────────────────────────────────

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_json())
    bot.process_new_updates([update])
    return jsonify({"ok": True})


@app.route("/reminder", methods=["GET", "POST"])
def reminder():
    """Called by cron-job.org at 8PM Addis time"""
    day = challenge_day_number()
    if day == 0:
        return jsonify({"ok": True, "msg": "Challenge not started"})

    res = supabase.table("members").select("*").execute()
    count = 0
    for profile in res.data:
        if profile.get("last_log") != current_day_str():
            try:
                bot.send_message(int(profile["user_id"]),
                    f"⏰ *Day {day}/90 — Daily Reminder!*\n\n"
                    f"You haven't logged today yet.\n"
                    f"🔥 Current streak: *{profile.get('streak', 0)} days*\n\n"
                    "Don't break it! Send /log now 💪",
                    parse_mode="Markdown")
                count += 1
            except Exception:
                pass
    return jsonify({"ok": True, "reminded": count})


@app.route("/leaderboard-post", methods=["GET", "POST"])
def leaderboard_post():
    """Called by cron-job.org at 6AM Addis time"""
    day = challenge_day_number()
    if day == 0:
        return jsonify({"ok": True, "msg": "Challenge not started"})

    try:
        bot.send_message(GROUP_ID, build_leaderboard_text(), parse_mode="Markdown")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=url)
    return jsonify({"ok": True, "webhook": url})

@app.route("/test-db", methods=["GET"])
def test_db():
    try:
        res = supabase.table("members").select("*").limit(1).execute()
        return jsonify({"ok": True, "data": res.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/test-bot", methods=["GET"])
def test_bot():
    try:
        bot.send_message(8103251058, "✅ Bot is working!")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "LockIn90 bot is running!"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))