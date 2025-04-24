
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
    
    if __name__ == '__main__':
        # در محیط توسعه
        if os.environ.get('FLASK_ENV') == 'development':
            app.run(host='0.0.0.0', port=8080, debug=True)
        else:
            # در محیط تولید از Gunicorn استفاده می‌شود
            import gunicorn.app.base

            class StandaloneApplication(gunicorn.app.base.BaseApplication):
                def __init__(self, app, options=None):
                    self.options = options or {}
                    self.application = app
                    super().__init__()

                def load_config(self):
                    for key, value in self.options.items():
                        self.cfg.set(key, value)

                def load(self):
                    return self.application

            options = {
                'bind': '0.0.0.0:8080',
                'workers': 1,
                'worker_class': 'gthread',
                'threads': 4,
                'timeout': 120
            }
            StandaloneApplication(app, options).run()
