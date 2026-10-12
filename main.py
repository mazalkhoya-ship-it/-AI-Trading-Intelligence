import asyncio
import os
from fastapi import FastAPI
import requests
from telegram.ext import ApplicationBuilder, CommandHandler
import uvicorn

# جلب التوكن بأمان دون إسقاط السيرفر إذا لم يجده
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

app = FastAPI(title="TradeAI Bot")


@app.get("/")
def home():
  return {"status": "ok", "bot_running": bool(TOKEN)}


async def start_cmd(update, context):
  await update.message.reply_text(
      "🚀 مرحباً بك! البوت يعمل الآن بنجاح 100% على Render."
  )


async def run_bot():
  if not TOKEN:
    print("❌ خطأ حرج: لم يتم العثور على TELEGRAM_BOT_TOKEN في Environment!")
    return

  # مسح الـ Webhook لتفادي أي تعارض مع Polling
  try:
    requests.get(
        f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true",
        timeout=10,
    )
  except Exception as e:
    print(f"تنبيه Webhook: {e}")

  # إعداد وتطبيق البوت
  application = ApplicationBuilder().token(TOKEN).build()
  application.add_handler(CommandHandler("start", start_cmd))

  await application.initialize()
  await application.start()
  await application.updater.start_polling(drop_pending_updates=True)
  print("✅ تم تشغيل الـ Polling واستقبال الرسائل بنجاح!")


@app.on_event("startup")
async def startup():
  asyncio.create_task(run_bot())


if __name__ == "__main__":
  port = int(os.getenv("PORT", 10000))
  uvicorn.run(app, host="0.0.0.0", port=port)
