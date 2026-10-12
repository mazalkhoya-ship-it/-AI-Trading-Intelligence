# AI Trading Intelligence — V1→V10 integrated

## ما تم دمجه
1. Data engine + 5000 historical candles
2. Multi-timeframe-ready analysis
3. Candlestick patterns + sequences
4. EMA/RSI/MACD/Bollinger/ATR/ADX/Momentum/SR
5. Historical similarity search
6. Random Forest ML ensemble
7. Market regime detection
8. Backtesting
9. Outcome database + architecture for walk-forward/self-learning
10. Telegram + Dashboard + webhook deployment

## تشغيل على Render
- ارفع الملفات إلى GitHub repository.
- Render > New > Web Service > اربط المستودع.
- Build: `pip install -r requirements.txt`
- Start: `python main.py`
- Environment: TELEGRAM_BOT_TOKEN = token from @BotFather
- بعد أول deploy خذ رابط `https://...onrender.com` وضعه في PUBLIC_URL ثم redeploy.

## Telegram
/start
/signal BTCUSDT 1m
/backtest BTCUSDT 1m
/status

لا ينفذ صفقات ولا يربط حسابات التداول. confidence ليست ضمانًا.
