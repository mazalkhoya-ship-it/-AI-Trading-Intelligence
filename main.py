import os, time, json, sqlite3, asyncio, threading
from typing import Optional
import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','')
PUBLIC_URL=os.getenv('PUBLIC_URL','').rstrip('/')
DB=os.getenv('DATABASE_PATH','trading_ai.db')
DEFAULT_SYMBOL=os.getenv('SYMBOL','BTCUSDT')
DEFAULT_INTERVAL=os.getenv('INTERVAL','1m')
BINANCE='https://api.binance.com'

app=FastAPI(title='AI Trading Intelligence')

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, chat_id INTEGER, symbol TEXT, interval TEXT, direction TEXT, score REAL, confidence REAL, regime TEXT, pattern TEXT, details TEXT, outcome TEXT DEFAULT 'PENDING');
    CREATE TABLE IF NOT EXISTS outcomes(signal_id INTEGER PRIMARY KEY, checked_at INTEGER, actual TEXT, win INTEGER);
    CREATE TABLE IF NOT EXISTS stats(key TEXT PRIMARY KEY, value REAL);
    '''); c.commit(); c.close()

def candles(symbol, interval, limit=1000, end=None):
    p={'symbol':symbol.upper(),'interval':interval,'limit':min(1000,limit)}
    if end is not None:p['endTime']=end
    r=requests.get(BINANCE+'/api/v3/klines',params=p,timeout=15); r.raise_for_status()
    return [{'t':int(x[0]),'o':float(x[1]),'h':float(x[2]),'l':float(x[3]),'c':float(x[4]),'v':float(x[5])} for x in r.json()]

def history(symbol, interval, total=5000):
    out=[]; end=None
    while len(out)<total:
        b=candles(symbol,interval,min(1000,total-len(out)),end)
        if not b: break
        out=b+out; end=b[0]['t']-1
        if len(b)<1000: break
        time.sleep(.12)
    return list({x['t']:x for x in out}.values())[-total:]

def df(rows):
    x=pd.DataFrame(rows); x=x.sort_values('t').reset_index(drop=True)
    for c in ['o','h','l','c','v']: x[c]=pd.to_numeric(x[c])
    x['ema9']=x.c.ewm(span=9,adjust=False).mean(); x['ema21']=x.c.ewm(span=21,adjust=False).mean(); x['ema50']=x.c.ewm(span=50,adjust=False).mean(); x['ema200']=x.c.ewm(span=200,adjust=False).mean()
    d=x.c.diff(); g=d.clip(lower=0).rolling(14).mean(); l=(-d.clip(upper=0)).rolling(14).mean(); rs=g/l.replace(0,np.nan); x['rsi']=100-100/(1+rs)
    e12=x.c.ewm(span=12,adjust=False).mean(); e26=x.c.ewm(span=26,adjust=False).mean(); x['macd']=e12-e26; x['macds']=x.macd.ewm(span=9,adjust=False).mean(); x['hist']=x.macd-x.macds
    mid=x.c.rolling(20).mean(); sd=x.c.rolling(20).std(); x['bbm']=mid; x['bbu']=mid+2*sd; x['bbl']=mid-2*sd
    pc=x.c.shift(1); tr=pd.concat([(x.h-x.l),(x.h-pc).abs(),(x.l-pc).abs()],axis=1).max(axis=1); x['atr']=tr.rolling(14).mean()
    x['mom20']=x.c.pct_change(20); x['sup']=x.l.rolling(20).min(); x['res']=x.h.rolling(20).max(); x['volz']=(x.v-x.v.rolling(30).mean())/x.v.rolling(30).std()
    # ADX-style trend strength
    up=x.h.diff(); down=-x.l.diff(); plus=np.where((up>down)&(up>0),up,0.0); minus=np.where((down>up)&(down>0),down,0.0)
    atr=x.atr.replace(0,np.nan); pdi=100*pd.Series(plus).rolling(14).mean()/atr; mdi=100*pd.Series(minus).rolling(14).mean()/atr; x['adx']=(100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)).rolling(14).mean()
    return x

def pat(rows):
    a,b=rows[-2],rows[-1]; body=abs(b['c']-b['o']); rng=max(b['h']-b['l'],1e-12); up=b['h']-max(b['o'],b['c']); lo=min(b['o'],b['c'])-b['l']
    if body/rng<.1:return 'DOJI'
    if lo>2*body and up<.8*body:return 'HAMMER'
    if up>2*body and lo<.8*body:return 'SHOOTING_STAR'
    if a['c']<a['o']<b['c'] and b['o']<=a['c'] and b['c']>=a['o']:return 'BULL_ENGULF'
    if a['c']>a['o']>b['c'] and b['o']>=a['c'] and b['c']<=a['o']:return 'BEAR_ENGULF'
    return 'NONE'

def seq(rows,n=8): return ''.join('U' if x['c']>x['o'] else 'D' if x['c']<x['o'] else 'N' for x in rows[-n:])

def similar(x, lookback=3000, k=200):
    if len(x)<100:return .5,0
    cols=['rsi','hist','mom20']; cur=x.iloc[-1]
    def vec(r):
        vals=[r[c] if pd.notna(r[c]) else 0 for c in cols]; s=r.atr if pd.notna(r.atr) and r.atr else max(r.c*.001,1e-9); vals += [(r.c-r.ema9)/s,(r.c-r.ema21)/s]; return np.nan_to_num(vals)
    v=vec(cur); arr=[]; start=max(50,len(x)-lookback)
    for i in range(start,len(x)-1): arr.append((float(np.linalg.norm(v-vec(x.iloc[i]))),1 if x.iloc[i+1].c>x.iloc[i].c else 0))
    arr.sort(); top=arr[:min(k,len(arr))]; up=sum(o for _,o in top)/len(top) if top else .5; return up,len(top)

def ml_predict(x):
    z=x.dropna().reset_index(drop=True)
    if len(z)<700:return None
    cols=['ema9','ema21','ema50','rsi','hist','atr','mom20','adx','volz']
    X=z[cols].iloc[:-1]; y=(z.c.shift(-1).iloc[:-1]>z.c.iloc[:-1]).astype(int)
    split=int(len(X)*.8); model=RandomForestClassifier(n_estimators=180,max_depth=8,min_samples_leaf=5,random_state=42,n_jobs=-1); model.fit(X.iloc[:split],y.iloc[:split]); p=model.predict_proba(X.iloc[[-1]])[0,1]
    return float(p)

def analyze(rows):
    x=df(rows); r=x.iloc[-1]; score=0; reasons=[]
    def add(v,s):
        nonlocal score; score+=v; reasons.append(s)
    add(1.5 if r.ema9>r.ema21 else -1.5,'EMA9/EMA21')
    add(1 if r.ema21>r.ema50 else -1,'EMA21/EMA50')
    add(1 if r.hist>0 else -1,'MACD')
    if 52<=r.rsi<=68:add(1,'RSI bullish zone')
    elif 32<=r.rsi<=48:add(-1,'RSI bearish zone')
    add(.5 if r.c>r.bbm else -.5,'Bollinger mid')
    if r.adx>25:add(.5,'Trend strength ADX>25')
    p=pat(rows)
    if p in ('BULL_ENGULF','HAMMER'):add(.8,p)
    if p in ('BEAR_ENGULF','SHOOTING_STAR'):add(-.8,p)
    up,n=similar(x); add((up-.5)*4 if n>=30 else 0,f'Historical UP {up*100:.1f}% ({n} matches)')
    mp=ml_predict(x); 
    if mp is not None:add((mp-.5)*3,'ML ensemble')
    direction='CALL' if score>=2.5 else 'PUT' if score<=-2.5 else 'NO TRADE'; confidence=min(95,50+abs(score)*7); confidence=min(confidence,59) if direction=='NO TRADE' else confidence
    regime='TREND UP' if r.ema9>r.ema21>r.ema50 else 'TREND DOWN' if r.ema9<r.ema21<r.ema50 else 'RANGE/MIXED'
    return {'direction':direction,'score':round(score,2),'confidence':round(confidence,1),'regime':regime,'pattern':p,'sequence':seq(rows),'historical_up':round(up*100,2),'matches':n,'ml_up':None if mp is None else round(mp*100,2),'rsi':None if pd.isna(r.rsi) else round(float(r.rsi),2),'reasons':reasons}

def backtest(rows, horizon=1):
    x=df(rows); sig=w=l=0
    for i in range(220,len(x)-horizon):
        r=x.iloc[i]; s=(1.5 if r.ema9>r.ema21 else -1.5)+(1 if r.ema21>r.ema50 else -1)+(1 if r.hist>0 else -1)
        if 52<=r.rsi<=68:s+=1
        elif 32<=r.rsi<=48:s-=1
        s+=.5 if r.c>r.bbm else -.5
        if abs(s)<2.5:continue
        sig+=1; actual=x.iloc[i+horizon].c>r.c; pred=s>0; w += pred==actual; l += pred!=actual
    return {'signals':sig,'wins':w,'losses':l,'win_rate':round(100*w/sig,2) if sig else 0}

def save_signal(chat,symbol,interval,a):
    c=db(); cur=c.execute('INSERT INTO signals(ts,chat_id,symbol,interval,direction,score,confidence,regime,pattern,details) VALUES(?,?,?,?,?,?,?,?,?,?)',(int(time.time()),chat,symbol,interval,a['direction'],a['score'],a['confidence'],a['regime'],a['pattern'],json.dumps(a,ensure_ascii=False))); c.commit(); sid=cur.lastrowid; c.close(); return sid

BOT=None

def text_signal(a,symbol,interval):
    ml='N/A' if a['ml_up'] is None else f"{a['ml_up']:.1f}%"
    return ('━━━━━━━━━━━━━━━━━━\n🧠 AI TRADING INTELLIGENCE\n━━━━━━━━━━━━━━━━━━\n'
    f'💹 {symbol} | {interval}\n🎯 {a["direction"]}\n💪 Evidence score: {a["confidence"]}%\n🧭 Regime: {a["regime"]}\n🕯 Pattern: {a["pattern"]}\n🔗 Sequence: {a["sequence"]}\n📚 Similar cases: {a["matches"]}\n📈 Historical UP: {a["historical_up"]}%\n🤖 ML UP: {ml}\n📊 RSI: {a["rsi"]}\n\n🔎 ' + ' | '.join(a['reasons'][:7]) + '\n\n⚠️ ليست ضمانًا ولا احتمال ربح مضمونًا.')

async def start(update,ctx):
    kb=[[InlineKeyboardButton('📊 Signal',callback_data='signal'),InlineKeyboardButton('🧪 Backtest',callback_data='backtest')],[InlineKeyboardButton('⚙️ Help',callback_data='help')]]
    await update.message.reply_text('🚀 AI Trading Intelligence\n\n/signal BTCUSDT 1m\n/backtest BTCUSDT 1m\n/status\n\nهذا محرك تحليل واختبار؛ لا ينفذ صفقات.',reply_markup=InlineKeyboardMarkup(kb))
async def help_cmd(update,ctx): await update.message.reply_text('الأوامر:\n/signal BTCUSDT 1m\n/backtest BTCUSDT 1m\n/status\n\nالفريمات: 1m 3m 5m 15m 30m 1h 4h 1d\n\nالمحرك يدمج المؤشرات والأنماط والتشابه التاريخي وML والـBacktest.')
async def status(update,ctx): await update.message.reply_text('🟢 ONLINE\n🧠 V1→V10 Integrated Engine\n📡 Binance public market data\n🧪 Backtest + Walk-forward-ready architecture\n🤖 ML ensemble\n⚠️ OTC غير مضمّن لأنه يحتاج مصدر OTC موثوق.')
async def signal_cmd(update,ctx):
    if len(ctx.args)!=2:return await update.message.reply_text('مثال: /signal BTCUSDT 1m')
    s,i=ctx.args[0].upper(),ctx.args[1]
    try:
        rows=history(s,i,5000); a=analyze(rows); save_signal(update.effective_chat.id,s,i,a); await update.message.reply_text(text_signal(a,s,i))
    except Exception as e: await update.message.reply_text('❌ '+str(e)[:800])
async def bt_cmd(update,ctx):
    if len(ctx.args)!=2:return await update.message.reply_text('مثال: /backtest BTCUSDT 1m')
    try:
        r=backtest(history(ctx.args[0].upper(),ctx.args[1],5000)); await update.message.reply_text(f'🧪 BACKTEST\nSignals: {r["signals"]}\nWins: {r["wins"]}\nLosses: {r["losses"]}\nWin rate: {r["win_rate"]}%')
    except Exception as e: await update.message.reply_text('❌ '+str(e)[:800])
async def buttons(update,ctx):
    q=update.callback_query; await q.answer()
    if q.data=='help': await q.edit_message_text('استخدم /signal BTCUSDT 1m أو /backtest BTCUSDT 1m')
    elif q.data=='signal': await q.edit_message_text(f'اكتب: /signal {DEFAULT_SYMBOL} {DEFAULT_INTERVAL}')
    elif q.data=='backtest': await q.edit_message_text(f'اكتب: /backtest {DEFAULT_SYMBOL} {DEFAULT_INTERVAL}')

async def build_bot():
    global BOT
    BOT=Application.builder().token(TOKEN).build()
    BOT.add_handler(CommandHandler('start',start)); BOT.add_handler(CommandHandler('help',help_cmd)); BOT.add_handler(CommandHandler('status',status)); BOT.add_handler(CommandHandler('signal',signal_cmd)); BOT.add_handler(CommandHandler('backtest',bt_cmd)); BOT.add_handler(CallbackQueryHandler(buttons))
    await BOT.initialize(); await BOT.start()
    if PUBLIC_URL:
        await BOT.bot.set_webhook(PUBLIC_URL+'/telegram/webhook')
    else:
        await BOT.updater.start_polling()

@app.get('/')
def root(): return {'status':'online','service':'AI Trading Intelligence','engine':'V1-V10 integrated'}
@app.get('/health')
def health(): return {'ok':True}
@app.post('/telegram/webhook')
async def webhook(request:Request):
    data=await request.json(); u=Update.de_json(data,BOT.bot); await BOT.process_update(u); return JSONResponse({'ok':True})
@app.get('/dashboard',response_class=HTMLResponse)
def dashboard():
    c=db(); rows=c.execute('SELECT symbol,interval,direction,confidence,regime,pattern,ts FROM signals ORDER BY id DESC LIMIT 50').fetchall(); c.close()
    tr=''.join(f"<tr><td>{r['symbol']}</td><td>{r['interval']}</td><td>{r['direction']}</td><td>{r['confidence']}</td><td>{r['regime']}</td><td>{r['pattern']}</td></tr>" for r in rows)
    return f'''<html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>body{{font-family:Arial;background:#0b1020;color:#eee;padding:20px}}.card{{background:#151d35;padding:18px;border-radius:16px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #334}}</style><div class="card"><h1>🧠 AI Trading Intelligence</h1><p>V1→V10 Integrated</p><table><tr><th>السوق</th><th>فريم</th><th>القرار</th><th>Score</th><th>Regime</th><th>Pattern</th></tr>{tr}</table></div></html>'''

def run():
    import uvicorn
    init_db()
    if not TOKEN: raise SystemExit('Missing TELEGRAM_BOT_TOKEN')
    async def starter(): await build_bot()
    asyncio.run(starter())
    uvicorn.run(app,host='0.0.0.0',port=int(os.getenv('PORT','10000')))

if __name__=='__main__': run()
