import os
from flask import Flask, request
import telegram

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
CHANNEL_ID = os.getenv("CHANNEL_ID")

bot = telegram.Bot(token=BOT_TOKEN)
app = Flask(__name__)

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    if update.message and update.message.text:
        user = update.message.from_user
        text = update.message.text.strip()
        msg = (
            f"📝 Отчёт от {user.full_name} (@{user.username})\n\n"
            f"{text}"
        )
        bot.send_message(chat_id=CHANNEL_ID, text=msg)
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render передаёт PORT через env
    app.run(host="0.0.0.0", port=port)
