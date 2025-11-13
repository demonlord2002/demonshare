import os
import logging
import random
import asyncio
from dotenv import load_dotenv
from threading import Thread

from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from pyrogram.enums import ParseMode

from pymongo import MongoClient
from flask import Flask

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
UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
ADMINS = [int(a.strip()) for a in ADMIN_IDS_STR.split(",") if a]

# ================= MongoDB Setup =================
client = MongoClient(MONGO_URI)
db = client['file_link_bot']
files_collection = db['files']
batch_collection = db['batch_sessions']
logging.info("✅ MongoDB Connected Successfully!")

# ================= Pyrogram Client =================
app = Client("PermaStoreBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= Helper Functions =================
def generate_random_string(length=8):
    return ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=length))

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
START_TEXT = "**🤖 Welcome to PermaStore Bot!**\n\nSend me any file, and I will give you a **permanent shareable link**!"
HELP_TEXT = "**How to use me:**\n1️⃣ Send any file.\n2️⃣ Add more files (optional).\n3️⃣ Click 'Get Free Link' for your share link."

NOTICE_TEXT = "⚠️ **Notice:** These files will be deleted after 10 minutes due to copyright policy.\nPlease save or forward them to your Saved Messages!"

# ================= Batch Functions =================
def get_batch(user_id):
    session = batch_collection.find_one({"user_id": user_id})
    return session['files'] if session else []

def add_to_batch(user_id, message_id):
    session = batch_collection.find_one({"user_id": user_id})
    if session:
        batch_collection.update_one({"user_id": user_id}, {"$push": {"files": message_id}})
    else:
        batch_collection.insert_one({"user_id": user_id, "files": [message_id]})

def clear_batch(user_id):
    batch_collection.delete_one({"user_id": user_id})

# ================= Send Files with Auto-Delete =================
async def send_files_with_notice(client: Client, user_id: int, message_ids: list):
    log_channel_id = await resolve_channel(client, LOG_CHANNEL)
    if not log_channel_id:
        return await client.send_message(user_id, "❌ LOG_CHANNEL not found. Contact admin.")

    sent_messages = []
    for msg_id in message_ids:
        try:
            sent = await client.copy_message(chat_id=user_id, from_chat_id=log_channel_id, message_id=msg_id)
            sent_messages.append(sent)
        except Exception as e:
            await client.send_message(user_id, f"❌ Error sending one file: {e}")

    if sent_messages:
        notice_msg = await client.send_message(user_id, NOTICE_TEXT)
        sent_messages.append(notice_msg)

        # Auto delete after 10 minutes
        await asyncio.sleep(600)
        for msg in sent_messages:
            try:
                await msg.delete()
            except:
                pass

# ================= Start Handler =================
@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user_name = message.from_user.first_name

    # If user opened link with batch ID
    if len(message.command) > 1:
        batch_id = message.command[1]
        record = files_collection.find_one({"_id": batch_id})
        if not record:
            await message.reply("❌ File not found or link expired.")
            return

        # Force Subscription
        if not await is_user_member(client, message.from_user.id):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Join Update Channel", url=f"https://t.me/{UPDATE_CHANNEL}")],
                [InlineKeyboardButton("✅ I Joined", callback_data=f"verify_{batch_id}")]
            ])
            await message.reply(
                f"👋 Hello {user_name}!\n\nYou must join our update channel to access this file.",
                reply_markup=keyboard
            )
            return

        # Send all files in batch
        await send_files_with_notice(client, message.from_user.id, record["message_ids"])
        return

    # Normal /start
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use", callback_data="help")],
        [InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{UPDATE_CHANNEL}")]
    ])
    await message.reply(START_TEXT, reply_markup=buttons)

# ================= Callback Query Handlers =================
@app.on_callback_query(filters.regex(r"^help$"))
async def help_callback(client, callback_query: CallbackQuery):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="start_back")]])
    await callback_query.message.edit_text(HELP_TEXT, reply_markup=kb)
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^start_back$"))
async def start_back(client, callback_query: CallbackQuery):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use", callback_data="help")],
        [InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{UPDATE_CHANNEL}")]
    ])
    await callback_query.message.edit_text(START_TEXT, reply_markup=kb)
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^verify_(.*)$"))
async def verify_callback(client, callback_query: CallbackQuery):
    batch_id = callback_query.data.split("_", 1)[1]
    user_id = callback_query.from_user.id

    if await is_user_member(client, user_id):
        await callback_query.answer("✅ Verified! Sending files...", show_alert=True)
        record = files_collection.find_one({"_id": batch_id})
        if record:
            await send_files_with_notice(client, user_id, record["message_ids"])
            await callback_query.message.delete()
        else:
            await callback_query.message.edit_text("❌ Files not found.")
    else:
        await callback_query.answer("❌ Join the update channel first.", show_alert=True)

# ================= File Handler (Admin Upload) =================
@app.on_message(filters.private & (filters.document | filters.video | filters.photo | filters.audio))
async def file_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        await message.reply("❌ Only admins can upload files.")
        return

    status = await message.reply("⏳ Uploading...")

    try:
        log_channel_id = await resolve_channel(client, LOG_CHANNEL)
        if not log_channel_id:
            await status.edit_text("❌ LOG_CHANNEL not found.")
            return

        forwarded = await message.forward(log_channel_id)
        add_to_batch(user_id, forwarded.id)
        batch_files = get_batch(user_id)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Get Free Link", callback_data="get_free_link")],
            [InlineKeyboardButton("➕ Add More Files", callback_data="add_more_files")],
            [InlineKeyboardButton("❌ Close", callback_data="close_batch")]
        ])

        await status.edit_text(
            f"✅ Batch Updated! You have **{len(batch_files)} file(s)** in queue.\nWhat next?",
            reply_markup=kb
        )
    except Exception as e:
        await status.edit_text(f"❌ Error: {e}")

# ================= Batch Buttons =================
@app.on_callback_query(filters.regex(r"^get_free_link$"))
async def get_free_link(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    batch_files = get_batch(user_id)
    if not batch_files:
        await callback_query.answer("❌ Your batch is empty!", show_alert=True)
        return

    batch_id = generate_random_string()
    files_collection.insert_one({
        "_id": batch_id,
        "message_ids": batch_files
    })

    bot_username = (await client.get_me()).username
    share_link = f"https://t.me/{bot_username}?start={batch_id}"

    await callback_query.message.edit_text(
        f"✅ Link Generated for **{len(batch_files)} files!**\n\n🔗 {share_link}\n\n⚠️ Files auto-delete after 10 mins."
    )

    await send_files_with_notice(client, user_id, batch_files)
    clear_batch(user_id)
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^add_more_files$"))
async def add_more_files(client: Client, callback_query: CallbackQuery):
    await callback_query.message.edit_text("✅ OK! Send more files to add.")
    await callback_query.answer()

@app.on_callback_query(filters.regex(r"^close_batch$"))
async def close_batch(client: Client, callback_query: CallbackQuery):
    clear_batch(callback_query.from_user.id)
    await callback_query.message.edit_text("❌ Batch closed. All files cleared.")
    await callback_query.answer()

# ================= Start Bot =================
if __name__ == "__main__":
    logging.info("🚀 Starting Flask web server...")
    Thread(target=run_flask).start()

    logging.info("🤖 Bot starting...")
    app.run()
