import os
from fastapi import FastAPI
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import uvicorn

TOKEN = "8750652390:AAEshkDnJ_PoiOMJYNLntYEBBQ9uTOxtFYE"

app = FastAPI(title="TradeAI Bot")


@app.get("/")
def home():
  return {"status": "ok", "message": "Bot is running perfectly!"}


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await update.message.reply_text(
      "🚀 أهلاً بك! البوت يعمل الآن بنجاح تام على تيليجرام."
  )


# تهيئة البوت وتشغيله كخدمة ويب متكاملة بدون تعليق
application = ApplicationBuilder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start_cmd))


@app.on_event("startup")
async def startup_event():
  # مسح الـ Webhook القديم أولاً لتفعيل الـ Polling
  try:
    requests.get(
        f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true",
        timeout=5,
    )
  except Exception:
    pass

  await application.initialize()
  await application.start()
  await application.updater.start_polling(drop_pending_updates=True)
  print("✅ تم تفعيل وتشغيل الـ Polling بنجاح!")


@app.on_event("shutdown")
async def shutdown_event():
  await application.stop()
  await application.shutdown()


if __name__ == "__main__":
  port = int(os.getenv("PORT", 10000))
  uvicorn.run(app, host="0.0.0.0", port=port)
