import os
import logging
from enum import Enum, auto

from flask import Flask, request
import telegram
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    Dispatcher,
)

# =====================
# ENVIRONMENT VARIABLES
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # -100XXXXXXXXXXXX
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")

if not BOT_TOKEN or not CHANNEL_ID:
    raise RuntimeError("BOT_TOKEN and CHANNEL_ID must be set in env vars")

# =============
# INITIAL SETUP
# =============
logging.basicConfig(level=logging.INFO)
bot = telegram.Bot(BOT_TOKEN)
app = Flask(__name__)

dp = Dispatcher(bot, None, use_context=True)


class Step(Enum):
    NONE = auto()
    PREACHING = auto()
    STUDIES = auto()
    PIONEER = auto()
    HOURS = auto()
    COMMENT = auto()


# ---------------
# Helper functions
# ---------------


def send_main_menu(chat_id: int, context: CallbackContext):
    """Sends the persistent main menu with the inline button and ensures /report appears."""
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📝 Отправить отчёт", callback_data="report")]]
    )
    context.bot.send_message(
        chat_id=chat_id,
        text="Нажмите кнопку ниже, чтобы заполнить новый отчёт:",
        reply_markup=keyboard,
    )


# -----------------
# Conversation flow
# -----------------


def start(update: Update, context: CallbackContext):
    """/start handler - show menu and register bot commands."""
    bot.set_my_commands(
        [("report", "Отправить отчёт")]
    )
    send_main_menu(update.effective_chat.id, context)


def report_cmd(update: Update, context: CallbackContext):
    """/report command - start the reporting flow (same as pressing the button)."""
    ask_preaching(update.effective_chat.id, context)
    context.user_data["step"] = Step.PREACHING


def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data
    step = context.user_data.get("step", Step.NONE)

    if data == "report":
        # Start flow
        ask_preaching(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data.clear()
        context.user_data["step"] = Step.PREACHING
        return

    if step == Step.PREACHING:
        context.user_data["preaching"] = "Да" if data == "yes" else "Нет"
        if data == "no":
            finish_report(update.effective_user, context, chat_id=query.message.chat_id)
            return
        # if "yes"
        ask_studies(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Step.STUDIES
        return

    if step == Step.PIONEER:
        context.user_data["pioneer"] = "Да" if data == "yes" else "Нет"
        if data == "no":
            # отправить отчёт с прочерками для часов и комментария
            finish_report(update.effective_user, context, chat_id=query.message.chat_id)
            return
        # If pioneer Yes – ask hours
        ask_hours(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Step.HOURS
        return


# ---------- questions helpers ------------

def ask_preaching(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Да", callback_data="yes"), InlineKeyboardButton("Нет", callback_data="no")]
        ]
    )
    if edit and msg:
        msg.edit_text("Участвовали ли вы в проповедническом служении?", reply_markup=keyboard)
    else:
        context.bot.send_message(chat_id, "Участвовали ли вы в проповедническом служении?", reply_markup=keyboard)


def ask_studies(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    text = "Сколько библейских изучений? (0-10)"
    if edit and msg:
        msg.edit_text(text)
    else:
        context.bot.send_message(chat_id, text)


def ask_pioneer(chat_id: int, context: CallbackContext):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Да", callback_data="yes"), InlineKeyboardButton("Нет", callback_data="no")]
        ]
    )
    context.bot.send_message(chat_id, "Пионер (подсобный пионер)?", reply_markup=keyboard)


def ask_hours(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    text = "Количество часов (0-100)"
    if edit and msg:
        msg.edit_text(text)
    else:
        context.bot.send_message(chat_id, text)


def ask_comment(chat_id: int, context: CallbackContext):
    context.bot.send_message(chat_id, "Комментарий (любой текст, можно пропустить, отправив '-'):")


# ------------- message handlers -------------

def text_handler(update: Update, context: CallbackContext):
    step = context.user_data.get("step")
    if not step:
        # ignore stray messages
        return

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if step == Step.STUDIES:
        if not text.isdigit() or not (0 <= int(text) <= 10):
            update.message.reply_text("Пожалуйста, введите число от 0 до 10")
            return
        context.user_data["studies"] = text
        ask_pioneer(chat_id, context)
        context.user_data["step"] = Step.PIONEER
        return

    if step == Step.HOURS:
        if not text.isdigit() or not (0 <= int(text) <= 100):
            update.message.reply_text("Введите число от 0 до 100")
            return
        context.user_data["hours"] = text
        ask_comment(chat_id, context)
        context.user_data["step"] = Step.COMMENT
        return

    if step == Step.COMMENT:
        context.user_data["comment"] = text
        finish_report(update.effective_user, context, chat_id=chat_id)
        return


# ------------- finishing -------------

def finish_report(user, context: CallbackContext, *, chat_id: int):
    data = context.user_data
    report = (
        f"{user.full_name} (@{user.username})\n\n"
        f"Участие: {data.get('preaching', '-') }\n"
        f"Изучения: {data.get('studies', '-') }\n"
        f"Пионер: {data.get('pioneer', '-') }\n"
        f"Часы: {data.get('hours', '-') }\n"
        f"Комментарий: {data.get('comment', '-') }"
    )

    # Отправить в канал
    context.bot.send_message(chat_id=CHANNEL_ID, text=report)

    # Подтвердить пользователю
    context.bot.send_message(chat_id, "Спасибо! Ваш отчёт отправлен.")

    # Показать главное меню снова
    send_main_menu(chat_id, context)
    context.user_data.clear()


# -------------- Flask webhook --------------

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return "ok"


# -------------- Flask ping --------------

@app.route("/ping")
def ping():
    return "pong"


# ------------ Register handlers ------------

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("report", report_cmd))
dp.add_handler(CallbackQueryHandler(button_handler))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))

# Entry point for Render local testing (optional)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
