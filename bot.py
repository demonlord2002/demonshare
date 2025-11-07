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
LOG_CHANNEL = os.environ.get("LOG_CHANNEL")
UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL")  # username without @
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
ADMINS = [int(a.strip()) for a in ADMIN_IDS_STR.split(",") if a]

# ================= MongoDB Setup =================
client = MongoClient(MONGO_URI)
db = client['file_link_bot']
files_collection = db['files']
settings_collection = db['settings']
logging.info("✅ MongoDB Connected Successfully!")

# ================= Pyrogram Client =================
app = Client("PermaStoreBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= Helper Functions =================
def generate_random_string(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

async def resolve_channel(client: Client, channel_identifier: str):
    try:
        if str(channel_identifier).startswith("-100") or str(channel_identifier).isdigit():
            return int(channel_identifier)
        chat = await client.get_chat(channel_identifier)
        return chat.id
    except Exception as e:
        logging.error(f"Failed to resolve channel '{channel_identifier}': {e}")
        return None

async def is_user_member(client: Client, user_id: int) -> bool:
    try:
        await client.get_chat_member(chat_id=f"@{UPDATE_CHANNEL}", user_id=user_id)
        return True
    except UserNotParticipant:
        return False
    except Exception as e:
        logging.error(f"Error checking membership for {user_id}: {e}")
        return False

# ================= Messages =================
START_TEXT = "_🤖 Welcome to PermaStore Bot!_\n\nSend me any file, and I will give you a *permanent shareable link* that never expires!"
HELP_TEXT = "_Here's how to use me:_\n1. Send any file (document, video, photo, audio).\n2. Receive a permanent link.\n3. Click the link to get your file anytime."

# ================= Bot Handlers =================
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user_name = message.from_user.first_name

    # Check if user clicked /start <file_id> link
    if len(message.command) > 1:
        file_id_str = message.command[1]
        file_record = files_collection.find_one({"_id": file_id_str})
        if not file_record:
            await message.reply("_🤔 File not found or link expired._", parse_mode="Markdown")
            return

        # Check membership
        if not await is_user_member(client, message.from_user.id):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Join Now", url=f"https://t.me/{UPDATE_CHANNEL}")],
                [InlineKeyboardButton("✅ I Have Joined", callback_data=f"verify_{file_id_str}")]
            ])
            await message.reply(f"_👋 Hello {user_name}!\n\nYou must join our update channel to access this file._",
                                reply_markup=keyboard, parse_mode="Markdown")
            return

        # If already joined, send file
        log_channel_id = await resolve_channel(client, LOG_CHANNEL)
        if not log_channel_id:
            await message.reply("_❌ LOG_CHANNEL not resolved. Contact admin._", parse_mode="Markdown")
            return
        try:
            await client.copy_message(chat_id=message.from_user.id,
                                      from_chat_id=log_channel_id,
                                      message_id=file_record['message_id'])
        except Exception as e:
            await message.reply(f"_❌ Error sending the file: {e}_", parse_mode="Markdown")
        return

    # Normal /start without file link
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use / Help", callback_data="help")],
        [InlineKeyboardButton("🔗 Join Update Channel", url=f"https://t.me/{UPDATE_CHANNEL}")]
    ])
    await message.reply(START_TEXT, reply_markup=buttons, parse_mode="Markdown")

@app.on_callback_query(filters.regex(r"^help$"))
async def help_callback(client: Client, callback_query: CallbackQuery):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="start_back")]])
    await callback_query.message.edit_text(HELP_TEXT, reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^start_back$"))
async def start_back_callback(client: Client, callback_query: CallbackQuery):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use / Help", callback_data="help")],
        [InlineKeyboardButton("🔗 Join Update Channel", url=f"https://t.me/{UPDATE_CHANNEL}")]
    ])
    await callback_query.message.edit_text(START_TEXT, reply_markup=buttons, parse_mode="Markdown")
    await callback_query.answer()

@app.on_message(filters.private & (filters.document | filters.video | filters.photo | filters.audio))
async def file_handler(client: Client, message: Message):
    status_msg = await message.reply("_⏳ Uploading your file..._", parse_mode="Markdown")
    try:
        log_channel_id = await resolve_channel(client, LOG_CHANNEL)
        if not log_channel_id:
            await status_msg.edit_text("_❌ LOG_CHANNEL not resolved. Contact admin._", parse_mode="Markdown")
            return
        forwarded = await message.forward(log_channel_id)
        file_id = generate_random_string()
        files_collection.insert_one({"_id": file_id, "message_id": forwarded.id})
        bot_username = (await client.get_me()).username
        share_link = f"https://t.me/{bot_username}?start={file_id}"
        await status_msg.edit_text(f"_✅ File uploaded!_\n\n🔗 Your permanent link:\n`{share_link}`",
                                   parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        await status_msg.edit_text(f"_❌ Error occurred: {e}_", parse_mode="Markdown")

@app.on_callback_query(filters.regex(r"^verify_"))
async def verify_callback(client: Client, callback_query: CallbackQuery):
    file_id = callback_query.data.split("_")[1]
    user_id = callback_query.from_user.id

    if await is_user_member(client, user_id):
        await callback_query.answer("_✅ Verified! Sending your file..._", show_alert=True)
        file_record = files_collection.find_one({"_id": file_id})
        if file_record:
            log_channel_id = await resolve_channel(client, LOG_CHANNEL)
            if not log_channel_id:
                await callback_query.message.edit_text("_❌ LOG_CHANNEL not resolved. Contact admin._", parse_mode="Markdown")
                return
            try:
                await client.copy_message(chat_id=user_id,
                                          from_chat_id=log_channel_id,
                                          message_id=file_record['message_id'])
                await callback_query.message.delete()
            except Exception as e:
                await callback_query.message.edit_text(f"_❌ Error sending file: {e}_", parse_mode="Markdown")
        else:
            await callback_query.message.edit_text("_🤔 File not found!_", parse_mode="Markdown")
    else:
        await callback_query.answer("_❌ You haven't joined yet. Please join and try again._", show_alert=True)

# ================= Start Bot =================
if __name__ == "__main__":
    logging.info("Starting Flask web server...")
    Thread(target=run_flask).start()

    logging.info("Bot is starting...")
    app.run()
