import os
import logging
import random
import string
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from pymongo import MongoClient
from flask import Flask
from threading import Thread

# ================= Flask Web Server =================
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)

# ================= Logging =================
logging.basicConfig(level=logging.INFO)

# ================= Load Environment Variables =================
load_dotenv()

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
LOG_CHANNEL = os.environ.get("LOG_CHANNEL")  # Numeric ID or public username
UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL")  # Must be username without @

ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
ADMINS = [int(a) for a in ADMIN_IDS_STR.split(",") if a]

# ================= MongoDB Setup =================
client = MongoClient(MONGO_URI)
db = client['file_link_bot']
files_collection = db['files']
settings_collection = db['settings']
logging.info("MongoDB Connected Successfully!")

# ================= Pyrogram Client =================
app = Client("PermaStoreBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= Helper Functions =================
def generate_random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

async def resolve_channel(client: Client, channel_identifier: str):
    if str(channel_identifier).startswith("-100") or str(channel_identifier).isdigit():
        return int(channel_identifier)
    try:
        chat = await client.get_chat(channel_identifier)
        return chat.id
    except:
        return None

async def is_user_member(client: Client, user_id: int) -> bool:
    try:
        await client.get_chat_member(chat_id=f"@{UPDATE_CHANNEL}", user_id=user_id)
        return True
    except UserNotParticipant:
        return False
    except:
        return False

def escape_md2(text: str) -> str:
    """Escape special characters for Markdown v2"""
    escape_chars = "_*[]()~`>#+-=|{}.!"
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

# ================= Messages =================
START_TEXT = escape_md2("""*PermaStore Bot* 🤖

Hey! I am PermaStore Bot.

Send me any file and I will give you a *permanent shareable link* which never expires!
""")

HELP_TEXT = escape_md2("""*Here's how to use me:*

1. Send Files: Send me any file, or forward multiple files at once.

2. Use the Menu: After you send a file, a menu will appear:
   - 🔗 *Get Free Link*: Creates a permanent link for all files in your batch.
   - ➕ *Add More Files*: Allows you to send more files to the current batch.

*Available Commands:*
/start - Restart the bot and clear any session.
/editlink - Edit an existing link you created.
/help - Show this help message.
""")

# ================= Bot Handlers =================
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use / Help", callback_data="help")],
        [InlineKeyboardButton("🔗 Join Now", url=f"https://t.me/{UPDATE_CHANNEL}")]
    ])
    await message.reply(START_TEXT, reply_markup=buttons, parse_mode="markdown_v2")

@app.on_callback_query(filters.regex(r"^help$"))
async def help_callback(client: Client, callback_query: CallbackQuery):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Back to Start", callback_data="start_back")]
    ])
    await callback_query.message.edit_text(HELP_TEXT, reply_markup=buttons, parse_mode="markdown_v2")
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^start_back$"))
async def start_back_callback(client: Client, callback_query: CallbackQuery):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use / Help", callback_data="help")],
        [InlineKeyboardButton("🔗 Join Now", url=f"https://t.me/{UPDATE_CHANNEL}")]
    ])
    await callback_query.message.edit_text(START_TEXT, reply_markup=buttons, parse_mode="markdown_v2")
    await callback_query.answer()

@app.on_message(filters.private & (filters.document | filters.video | filters.photo | filters.audio))
async def file_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if not await is_user_member(client, user_id):
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{UPDATE_CHANNEL}")],
            [InlineKeyboardButton("✅ I Have Joined", callback_data="verify_join")]
        ])
        await message.reply("You must join the update channel first!", reply_markup=buttons)
        return

    status_msg = await message.reply("⏳ Uploading your file...", quote=True)
    try:
        log_channel_id = await resolve_channel(client, LOG_CHANNEL)
        forwarded = await message.forward(log_channel_id)
        file_id = generate_random_string()
        files_collection.insert_one({'_id': file_id, 'message_id': forwarded.id})
        bot_username = (await client.get_me()).username
        share_link = f"https://t.me/{bot_username}?start={file_id}"
        await status_msg.edit_text(f"✅ File uploaded successfully!\n\n🔗 Permanent Link: `{escape_md2(share_link)}`", parse_mode="markdown_v2")
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")

@app.on_callback_query(filters.regex(r"^verify_join$"))
async def verify_join_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if await is_user_member(client, user_id):
        await callback_query.answer("✅ Verified! You can now send your file.", show_alert=True)
        await callback_query.message.delete()
    else:
        await callback_query.answer("❌ You haven't joined yet. Join first!", show_alert=True)

# ================= Start Bot =================
if __name__ == "__main__":
    logging.info("Starting Flask server...")
    Thread(target=run_flask).start()
    logging.info("Bot starting...")
    app.run()
