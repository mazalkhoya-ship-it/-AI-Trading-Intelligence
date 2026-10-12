import asyncio
import os
from fastapi import FastAPI
import requests
from telegram.ext import ApplicationBuilder, CommandHandler
import uvicorn

# التوكن موضوع مباشرة لضمان عدم حدوث أي خطأ في قراءة متغيرات المنصة
TOKEN = "8750652390:AAEshkDnJ_PoiOMJYNLntYEBBQ9uTOxtFYE"

app = FastAPI(title="TradeAI Bot")


@app.get("/")
def home():
  return {"status": "ok", "message": "Bot is active and running!"}


async def start_cmd(update, context):
  await update.message.reply_text(
      "🚀 أهلاً بك! البوت يعمل الآن بنجاح تام على تيليجرام."
  )


async def run_bot():
  # مسح الـ Webhook القديم لضمان عمل الـ Polling بدون تعارض
  try:
    requests.get(
        f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true",
        timeout=10,
    )
  except Exception as e:
    print(f"Webhook error: {e}")

  application = ApplicationBuilder().token(TOKEN).build()
  application.add_handler(CommandHandler("start", start_cmd))

  await application.initialize()
  await application.start()
  await application.updater.start_polling(drop_pending_updates=True)
  print("✅ تم تشغيل بوت تيليجرام والاستماع للرسائل بنجاح!")


@app.on_event("startup")
async def startup():
  asyncio.create_task(run_bot())


if __name__ == "__main__":
  port = int(os.getenv("PORT", 10000))
  uvicorn.run(app, host="0.0.0.0", port=port)
