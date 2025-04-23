from flask import Flask
from models import init_db, load_default_menu

app = Flask(__name__)

@app.route('/')
def index():
    return 'Telegram Bot Service is Running'

if __name__ == '__main__':
    # ایجاد اتصال به دیتابیس و بارگذاری منوی پیش‌فرض
    db_session = init_db()
    load_default_menu(db_session)
    
    app.run(host='0.0.0.0', port=5000)