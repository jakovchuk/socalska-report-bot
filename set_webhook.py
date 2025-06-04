import os
import telegram

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
RENDER_URL = os.getenv("RENDER_URL")  # Пример: https://mybot.onrender.com

bot = telegram.Bot(token=BOT_TOKEN)
webhook_url = f"{RENDER_URL}/{WEBHOOK_SECRET}"
bot.set_webhook(url=webhook_url)
print(f"Webhook установлен: {webhook_url}")