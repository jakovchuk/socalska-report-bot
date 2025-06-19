import os
import telegram

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
PYTHON_ANYWHERE_URL = os.getenv("PYTHON_ANYWHERE_URL")

bot = telegram.Bot(token=BOT_TOKEN)
webhook_url = f"{PYTHON_ANYWHERE_URL}/{WEBHOOK_SECRET}"
bot.set_webhook(url=webhook_url)
print(f"Webhook установлен: {webhook_url}")