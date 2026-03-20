import logging
import asyncio
import feedparser
import sqlite3
import requests
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = "8618220272:AAHBzURQt0ILCgR6rqlzS7O_tnnqbRlBxVY"
NITTER_BASE = "https://lightbrd.com"
POLL_INTERVAL = 900  # 15 minutes

# --- Database ---
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_posts (
            post_id TEXT PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
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

# --- RSS Fetching ---
def fetch_posts(username):
    url = f"{NITTER_BASE}/{username}/rss"
    try:
        feed = feedparser.parse(url)
        return feed.entries
    except Exception as e:
        logging.error(f"Failed to fetch {username}: {e}")
        return []

def parse_entry(entry, username):
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    post_id = entry.get("id", "")
    published = entry.get("published", "")

    # Detect repost
    is_repost = title.startswith("RT by")
    reposted_from = None
    if is_repost:
        # title format: "RT by @username: @original: text"
        try:
            reposted_from = title.split(":")[1].strip().split()[0]
        except:
            reposted_from = "unknown"

    # Extract image if any
    image_url = None
    if "media_thumbnail" in entry:
        image_url = entry.media_thumbnail[0].get("url")
    elif "media_content" in entry:
        image_url = entry.media_content[0].get("url")

    # Clean text
    import re
    text = re.sub('<[^<]+?>', '', summary).strip()

    # Format date
    try:
        dt = datetime(*entry.published_parsed[:6])
        date_str = dt.strftime("%H:%M · %b %d, %Y")
    except:
        date_str = published

    return {
        "post_id": post_id,
        "username": username,
        "text": text,
        "is_repost": is_repost,
        "reposted_from": reposted_from,
        "image_url": image_url,
        "date": date_str
    }

def format_message(post):
    if post["is_repost"]:
        header = f"🔁 @{post['username']} reposted {post['reposted_from']}"
    else:
        header = f"🐦 @{post['username']}"

    msg = f"{header}\n─────────────\n{post['text']}\n─────────────\n🕐 {post['date']}"
    return msg

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
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
        await update.message.reply_text("Tracked accounts:\n" + "\n".join(f"• @{a}" for a in accounts))

# --- Poller ---
async def poll(bot: Bot):
    while True:
        chat_id = get_chat_id()
        if chat_id:
            for username in get_accounts():
                entries = fetch_posts(username)
                for entry in reversed(entries):
                    post = parse_entry(entry, username)
                    if not is_sent(post["post_id"]):
                        msg = format_message(post)
                        try:
                            if post["image_url"]:
                                await bot.send_photo(chat_id=chat_id, photo=post["image_url"], caption=msg)
                            else:
                                await bot.send_message(chat_id=chat_id, text=msg)
                            mark_sent(post["post_id"])
                        except Exception as e:
                            logging.error(f"Send error: {e}")
        await asyncio.sleep(POLL_INTERVAL)

# --- Main ---
async def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_accounts))

    asyncio.create_task(poll(app.bot))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
