
from flask import Flask
from models import init_db, load_default_menu, Base
from sqlalchemy import create_engine
import asyncio
from bot_new import main as bot_main
import threading
import os

app = Flask(__name__)

@app.route('/')
def index():
    return 'Telegram Bot Service is Running'

def run_bot():
    asyncio.run(bot_main())

if __name__ == '__main__':
    # ایجاد اتصال به دیتابیس
    database_url = os.environ.get('DATABASE_URL')
    engine = create_engine(database_url)
    
    # ایجاد تمام جداول
    Base.metadata.create_all(engine)
    
    # ایجاد اتصال به دیتابیس و بارگذاری منوی پیش‌فرض
    db_session = init_db()
    load_default_menu(db_session)
    
    # راه‌اندازی ربات در یک thread جداگانه
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # راه‌اندازی Flask
    app.run(host='0.0.0.0', port=8080)
