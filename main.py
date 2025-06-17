import os
import logging
from enum import Enum, auto
from datetime import datetime, time as dtime

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
    JobQueue,
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

# Set up JobQueue for monthly reminders
ojq = JobQueue()
ojq.set_dispatcher(dp)
ojq.start()

# Russian month names for report header
RU_MONTHS = [None,
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]

# Helper: compute previous month name and year
def get_report_period():
    now = datetime.now()
    # previous month logic
    if now.month == 1:
        year = now.year - 1
        month = 12
    else:
        year = now.year
        month = now.month - 1
    month_name = RU_MONTHS[month]
    return month_name, year

class Steps(Enum):
    NONE = auto()
    PREACHING = auto()
    STUDIES = auto()
    PIONEER = auto()
    HOURS = auto()
    COMMENT = auto()

# Reminder callbacks
def monthly_reminder(context: CallbackContext):
    month_name, year = get_report_period()
    chat_id = context.job.context
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📝 Отправить отчёт", callback_data="report")]]
    )
    context.bot.send_message(
        chat_id=chat_id,
        text=f"Не забудьте сдать отчёт за {month_name} {year}!",
        reply_markup=keyboard,
    )

def daily_check(context: CallbackContext):
    if datetime.now().day == 1:
        monthly_reminder(context)

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
    chat_id = update.effective_chat.id
    bot.set_my_commands([("report", "Отправить отчёт")])
    send_main_menu(update.effective_chat.id, context)

    # schedule reminder once per chat
    if not context.chat_data.get("reminder_scheduled"):
        context.job_queue.run_daily(
            callback=daily_check,
            time=dtime(hour=9, minute=0),  # Kyiv time assumed server TZ
            context=chat_id
        )
        context.chat_data["reminder_scheduled"] = True


def report_cmd(update: Update, context: CallbackContext):
    """/report command - start the reporting flow (same as pressing the button)."""
    ask_preaching(update.effective_chat.id, context)
    context.user_data["step"] = Steps.PREACHING


def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    data = query.data
    step = context.user_data.get("step", Steps.NONE)

    # Back navigation
    if data == "back":
        _go_back(step, query, context)
        return

    # Start flow via menu
    if data == "report":
        ask_preaching(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data.clear()
        context.user_data["step"] = Steps.PREACHING
        return

    # PREACHING
    if step == Steps.PREACHING:
        context.user_data["preaching"] = "Да" if data == "yes" else "Нет"
        if data == "no":
            finish_report(update.effective_user, context, chat_id=query.message.chat_id)
            return
        ask_studies(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Steps.STUDIES
        return

    # STUDIES
    if step == Steps.STUDIES:
        context.user_data["studies"] = data
        ask_pioneer(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Steps.PIONEER
        return

    # PIONEER
    if step == Steps.PIONEER:
        context.user_data["pioneer"] = "Да" if data == "yes" else "Нет"
        if data == "no":
            ask_comment(query.message.chat_id, context, edit=True, msg=query.message)
            context.user_data["step"] = Steps.COMMENT
            return
        ask_hours(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Steps.HOURS
        return

    # COMMENT skip
    if step == Steps.COMMENT and data == "skip_comment":
        context.user_data['comment'] = '-'
        finish_report(update.effective_user, context, chat_id=query.message.chat_id)
        return

# ---------- navigation helper ------------
def _go_back(step, query, context):
    if step == Steps.STUDIES:
        ask_preaching(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Steps.PREACHING
    elif step == Steps.PIONEER:
        ask_studies(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Steps.STUDIES
    elif step == Steps.HOURS:
        ask_pioneer(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Steps.PIONEER
    elif step == Steps.COMMENT:
        if context.user_data["pioneer"] == "Да":
            ask_hours(query.message.chat_id, context, edit=True, msg=query.message)
            context.user_data["step"] = Steps.HOURS
            return
        ask_pioneer(query.message.chat_id, context, edit=True, msg=query.message)
        context.user_data["step"] = Steps.PIONEER

# ---------- questions helpers ------------

def ask_preaching(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    text = "Участвовали ли вы в проповедническом служении?"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("☑️ Да", callback_data="yes"),
                InlineKeyboardButton("❌ Нет", callback_data="no"),
            ]
        ]
    )
    if edit and msg:
        sent = msg.edit_text(text, reply_markup=keyboard)
    else:
        sent = context.bot.send_message(chat_id, text, reply_markup=keyboard)
    context.user_data.setdefault("to_delete", []).append(sent.message_id)


def ask_studies(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    text = "Количество библейских изучений:"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Нет", callback_data=0),
                InlineKeyboardButton("1", callback_data=1),
                InlineKeyboardButton("2", callback_data=2),
                InlineKeyboardButton("3", callback_data=3),
            ],
            [
                InlineKeyboardButton("4", callback_data=4),
                InlineKeyboardButton("5", callback_data=5),
                InlineKeyboardButton("6", callback_data=6),
                InlineKeyboardButton("7", callback_data=7),
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            ]
        ]
    )
    if edit and msg:
        sent = msg.edit_text(text, reply_markup=keyboard)
    else:
        sent = context.bot.send_message(chat_id, text, reply_markup=keyboard)
    context.user_data.setdefault("to_delete", []).append(sent.message_id)    


def ask_pioneer(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    text = "Пионер (подсобный пионер)?"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("☑️ Да", callback_data="yes"),
                InlineKeyboardButton("❌ Нет", callback_data="no"),
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            ]
        ]
    )
    if edit and msg:
        sent = msg.edit_text(text, reply_markup=keyboard)
    else:
        sent = context.bot.send_message(chat_id, text, reply_markup=keyboard)
    context.user_data.setdefault("to_delete", []).append(sent.message_id)


def ask_hours(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    text = "Количество часов (введите число от 1 до 100 в строке ниже):"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            ]
        ]
    )
    if edit and msg:
        sent = msg.edit_text(text, reply_markup=keyboard)
    else:
        sent = context.bot.send_message(chat_id, text, reply_markup=keyboard)
    context.user_data.setdefault("to_delete", []).append(sent.message_id)


def ask_comment(chat_id: int, context: CallbackContext, *, edit=False, msg=None):
    text = "Комментарий (введите любой текст в строке ниже или нажмите Пропустить):"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="back"),
                InlineKeyboardButton("Пропустить", callback_data="skip_comment")
            ],
        ]
    )
    if edit and msg:
        sent = msg.edit_text(text, reply_markup=keyboard)
    else:
        sent = context.bot.send_message(chat_id, text, reply_markup=keyboard)
    context.user_data.setdefault("to_delete", []).append(sent.message_id)


# ------------- message handlers -------------

def text_handler(update: Update, context: CallbackContext):
    step = context.user_data.get("step")
    if not step:
        return

    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    context.user_data.setdefault("to_delete", []).append(update.message.message_id)

    if step == Steps.HOURS:
        if not text.isdigit() or not (1 <= int(text) <= 100):
            update.message.reply_text("Введите число от 1 до 100")
            return
        context.user_data["hours"] = text
        ask_comment(chat_id, context)
        context.user_data["step"] = Steps.COMMENT
        return

    if step == Steps.COMMENT:
        context.user_data['comment'] = text
        finish_report(update.effective_user, context, chat_id=chat_id)
        return


# ------------- finishing -------------

def build_report(user_data):
    keys = ['preaching', 'studies', 'pioneer', 'hours', 'comment']
    labels = ['Участие',   'Изучения', 'Пионер', 'Часы',  'Комментарий']
    values = {k: user_data.get(k, '-') for k in keys}
    
    if values['preaching'] == 'Нет':
        blank_keys = ['studies', 'pioneer', 'hours', 'comment']
    elif values['pioneer'] == 'Нет':
        blank_keys = ['hours']
    else:
        blank_keys = []
    
    for k in blank_keys:
        values[k] = '-'
    
    lines = [
        f"{label}: {values[key]}"
        for label, key in zip(labels, keys)
    ]
    return "\n".join(lines)


def finish_report(user, context: CallbackContext, *, chat_id: int):
    month_name, year = get_report_period()
    # Prepare report data
    report = build_report(context.user_data)

    # Send report to channel
    if user.username is None:
        user_name = ""
    else:
        user_name = "(@" + user.username.strip('@') + ")"

    report_text = (
        f"Отчёт за {month_name} {year}\n"
        f"от {user.full_name} {user_name}\n\n"
        f"{report}"
    )
    context.bot.send_message(chat_id=CHANNEL_ID, text=report_text)

    # Send confirmation to user
    confirmation_text = (
        "Спасибо!\n\n"
        f"Ваш отчёт за {month_name} {year} отправлен.\n\n"
        f"{report}"
    )
    context.bot.send_message(chat_id, confirmation_text)

    # clean up the back-and-forth
    for msg_id in context.user_data.get("to_delete", []):
        try:
            context.bot.delete_message(chat_id, msg_id)
        except telegram.error.BadRequest:
            # e.g. message too old or missing permissions
            pass

    # Clear user data
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

# -------------- Run application --------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
