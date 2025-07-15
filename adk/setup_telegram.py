import asyncio
from main import set_telegram_webhook, get_telegram_webhook_info, delete_telegram_webhook

# Replace this with the URL ngrok gave you
NGROK_PUBLIC_URL = "https://456119b50614.ngrok-free.app"

# Set the webhook
asyncio.run(set_telegram_webhook(NGROK_PUBLIC_URL))

# (Optional) Verify the webhook is set
asyncio.run(get_telegram_webhook_info())

# (Optional) To remove the webhook later:
# asyncio.run(delete_telegram_webhook())