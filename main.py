import logging
import asyncio
import feedparser
import sqlite3
import re
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = "8618220272:AAHBzURQt0ILCgR6rqlzS7O_tnnqbRlBxVY"
NITTER_BASE = "https://xcancel.com"
POLL_INTERVAL = 900  # 15 minutes

# --- Database ---
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS accounts (username TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS sent_posts (post_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

def save_chat_id(chat_id):
    conn = sqlite3.connect("bot.db")
    conn.execute("INSERT OR REPLACE INTO config VALUES ('chat_id', ?)", (str(chat_id),))
    conn.commit()
    conn.close()

def get_chat_id():
    conn = sqlite3.connect("bot.db")
    row = conn.execute("SELECT value FROM config WHERE key='chat_id'").fetchone()
    conn.close()
    return row[0] if row else None

def get_accounts():
    conn = sqlite3.connect("bot.db")
    rows = conn.execute("SELECT username FROM accounts").fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_account(username):
    conn = sqlite3.connect("bot.db")
    conn.execute("INSERT OR IGNORE INTO accounts VALUES (?)", (username,))
    conn.commit()
    conn.close()

def remove_account(username):
    conn = sqlite3.connect("bot.db")
    conn.execute("DELETE FROM accounts WHERE username=?", (username,))
    conn.commit()
    conn.close()

def is_sent(post_id):
    conn = sqlite3.connect("bot.db")
    row = conn.execute("SELECT 1 FROM sent_posts WHERE post_id=?", (post_id,)).fetchone()
    conn.close()
    return row is not None

def mark_sent(post_id):
    conn = sqlite3.connect("bot.db")
    conn.execute("INSERT OR IGNORE INTO sent_posts VALUES (?)", (post_id,))
    conn.commit()
    conn.close()

# --- RSS Parsing ---
def fetch_entries(username):
    url = f"{NITTER_BASE}/{username}/rss"
    try:
        return feedparser.parse(url).entries
    except Exception as e:
        logging.error(f"Fetch error for {username}: {e}")
        return []

def parse_entry(entry, username):
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    post_id = entry.get("id", "")

    is_repost = title.startswith("RT by")
    reposted_from = None
    if is_repost:
        try:
            reposted_from = title.split(":")[1].strip().split()[0]
        except:
            reposted_from = "unknown"

    image_url = None
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        image_url = entry.media_thumbnail[0].get("url")
    elif hasattr(entry, "media_content") and entry.media_content:
        image_url = entry.media_content[0].get("url")

    text = re.sub('<[^<]+?>', '', summary).strip()

    try:
        dt = datetime(*entry.published_parsed[:6])
        date_str = dt.strftime("%H:%M · %b %d, %Y")
    except:
        date_str = ""

    return {
        "post_id": post_id,
        "username": username,
        "text": text,
        "is_repost": is_repost,
        "reposted_from": reposted_from,
        "image_url": image_url,
        "date": date_str,
    }

def format_message(post):
    if post["is_repost"]:
        header = f"🔁 @{post['username']} reposted {post['reposted_from']}"
    else:
        header = f"🐦 @{post['username']}"
    return f"{header}\n─────────────\n{post['text']}\n─────────────\n🕐 {post['date']}"

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    await update.message.reply_text("✅ Bot activated! Use /add <username> to track accounts.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add <username>")
        return
    username = context.args[0].lstrip("@").strip()
    add_account(username)
    await update.message.reply_text(f"✅ Now tracking @{username}")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /remove <username>")
        return
    username = context.args[0].lstrip("@").strip()
    remove_account(username)
    await update.message.reply_text(f"🗑️ Removed @{username}")

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accounts = get_accounts()
    if not accounts:
        await update.message.reply_text("No accounts tracked yet.")
    else:
        await update.message.reply_text("Tracked:\n" + "\n".join(f"• @{a}" for a in accounts))

# --- Poller ---
async def poll(bot: Bot):
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        chat_id = get_chat_id()
        if not chat_id:
            continue
        for username in get_accounts():
            for entry in reversed(fetch_entries(username)):
                post = parse_entry(entry, username)
                if is_sent(post["post_id"]):
                    continue
                msg = format_message(post)
                try:
                    if post["image_url"]:
                        await bot.send_photo(chat_id=chat_id, photo=post["image_url"], caption=msg)
                    else:
                        await bot.send_message(chat_id=chat_id, text=msg)
                    mark_sent(post["post_id"])
                except Exception as e:
                    logging.error(f"Send error: {e}")

# --- Main ---
async def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_accounts))

    async with app:
        await app.start()
        await app.updater.start_polling()
        await poll(app.bot)

if __name__ == "__main__":
    asyncio.run(main())
