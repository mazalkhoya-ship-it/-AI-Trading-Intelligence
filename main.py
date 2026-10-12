import asyncio
import os
import sqlite3
import threading
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sklearn.ensemble import RandomForestClassifier
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
import uvicorn
import requests
import numpy as np
import pandas as pd

# قراءة المتغيرات والبيانات الأساسية
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
PUBLIC_URL = os.getenv('PUBLIC_URL', '').rstrip('/')
DB = os.getenv('DATABASE_PATH', 'trading_ai.db')
DEFAULT_SYMBOL = os.getenv('SYMBOL', 'BTCUSDT')
DEFAULT_INTERVAL = os.getenv('INTERVAL', '1m')
BINANCE = 'https://api.binance.com'

app = FastAPI(title='AI Trading Intelligence')

# إعداد قاعدة البيانات
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    conn = db()
    conn.execute('''CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        symbol TEXT,
        action TEXT,
        price REAL,
        conf REAL
    )''')
    conn.commit()
    conn.close()

init_db()

# مسار الصفحة الرئيسية للتحقق من عمل السيرفر
@app.get('/')
def read_root():
    return {"status": "ok", "message": "AI Trading Intelligence Bot is running live!"}

# دوال البوت وأوامره
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 أهلاً بك في بوت ذكاء التداول (AI Trading Intelligence)!\n\n"
        "البوت يعمل بنجاح وجاهز لتقديم تحليلات السوق والإشارات.\n"
        "استخدم الأوامر التالية:\n"
        "/start - إرسال القائمة الرئيسية\n"
        "/status - فحص حالة النظام والاتصال"
    )
    await update.message.reply_text(welcome_text)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 الحالة: النظام يعمل بنجاح ومتصل بـ Render و Telegram Polling.")

# دالة تشغيل بوت التيليجرام بالتزامن مع FastAPI
async def start_telegram_bot():
    if not TOKEN:
        print("تحذير: TELEGRAM_BOT_TOKEN غير موجود!")
        return
    
    # مسح أي Webhook قديم لتفادي التعارض وتفعيل الـ Polling
