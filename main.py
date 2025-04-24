
from flask import Flask
from models import init_db, load_default_menu
import asyncio
from bot_new import main as bot_main
import threading

app = Flask(__name__)

@app.route('/')
def index():
    return 'Telegram Bot Service is Running'

def run_bot():
    asyncio.run(bot_main())

if __name__ == '__main__':
    # ایجاد اتصال به دیتابیس و بارگذاری منوی پیش‌فرض
    db_session = init_db()
    load_default_menu(db_session)
    
    # راه‌اندازی ربات در یک thread جداگانه
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # راه‌اندازی Flask
    app.run(host='0.0.0.0', port=8080)
