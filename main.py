import os
import logging
import threading
from flask import Flask, request
import telegram
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Dispatcher,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
)

# ====== ENV VARS ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")

if not BOT_TOKEN or not CHANNEL_ID:
    raise RuntimeError("BOT_TOKEN and CHANNEL_ID must be set as env vars!")

# ====== Telegram setup ======
bot = telegram.Bot(token=BOT_TOKEN)
# Use a Dispatcher without a Queue (sufficient for light‑weight bots via webhook)
dispatcher = Dispatcher(bot=bot, update_queue=None, use_context=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Conversation states ======
PREACH, STUDIES, HOURS, COMMENT = range(4)

# ====== Handler callbacks ======

def start(update: Update, context: CallbackContext):
    """Send a button to begin the report."""
    keyboard = [[InlineKeyboardButton("📝 Отправить отчёт", callback_data="start_report")]]
    update.message.reply_text(
        "Привет! Нажмите кнопку ниже, чтобы отправить отчёт.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def start_report_cb(update: Update, context: CallbackContext):
    """Entry‑point after the user presses the main button."""
    query = update.callback_query
    query.answer()
    # Reset per‑user data
    context.user_data.clear()
    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data="preach_yes"),
            InlineKeyboardButton("Нет", callback_data="preach_no"),
        ]
    ]
    query.edit_message_text(
        "1️⃣ Участвовали ли вы в проповеди?", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PREACH


def preach_answer_cb(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    participated = query.data == "preach_yes"
    context.user_data["preach"] = "Да" if participated else "Нет"

    if not participated:
        # Skip rest, send report immediately
        context.user_data["studies"] = "‑"
        context.user_data["hours"] = "‑"
        context.user_data["comment"] = "‑"
        send_report(update.effective_user, context)
        query.edit_message_text("Спасибо! Отчёт отправлен.")
        return ConversationHandler.END

    # Ask for number of studies
    query.edit_message_text("2️⃣ Количество изучений (1‑10):")
    return STUDIES


def studies_msg(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 10):
        update.message.reply_text("Введите число от 1 до 10.")
        return STUDIES
    context.user_data["studies"] = text
    update.message.reply_text("3️⃣ Количество часов (0‑100):")
    return HOURS


def hours_msg(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if not text.isdigit() or not (0 <= int(text) <= 100):
        update.message.reply_text("Введите число от 0 до 100.")
        return HOURS
    context.user_data["hours"] = text
    update.message.reply_text("4️⃣ Комментарий (или ""-"" если нет):")
    return COMMENT


def comment_msg(update: Update, context: CallbackContext):
    context.user_data["comment"] = update.message.text.strip() or "‑"
    send_report(update.effective_user, context)
    update.message.reply_text("Спасибо! Отчёт отправлен.")
    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Отчёт отменён.")
    return ConversationHandler.END


def send_report(user, context: CallbackContext):
    """Compose and forward the report to the channel in a thread to keep webhook fast."""

    def _send():
        ud = context.user_data
        msg = (
            f"📝 Отчёт от {user.full_name} (@{user.username})\n\n"
            f"Участие в проповеди: {ud['preach']}\n"
            f"Изучений: {ud['studies']}\n"
            f"Часы: {ud['hours']}\n"
            f"Комментарий: {ud['comment']}"
        )
        bot.send_message(chat_id=CHANNEL_ID, text=msg)

    threading.Thread(target=_send).start()


# ====== Register handlers ======
conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_report_cb, pattern="^start_report$")],
    states={
        PREACH: [CallbackQueryHandler(preach_answer_cb, pattern="^preach_(yes|no)$")],
        STUDIES: [MessageHandler(Filters.text & ~Filters.command, studies_msg)],
        HOURS: [MessageHandler(Filters.text & ~Filters.command, hours_msg)],
        COMMENT: [MessageHandler(Filters.text & ~Filters.command, comment_msg)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    allow_reentry=True,
)

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(conv)

# ====== Flask webhook ======
app = Flask(__name__)

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/ping")
def ping():
    return "pong"

# Entry point for Render local testing (optional)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
