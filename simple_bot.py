import os
import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

# فعال کردن لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# تابع‌های پردازش دستورها
def start(update, context):
    """واکنش به دستور /start"""
    update.message.reply_text('سلام! خوش آمدید به ربات تلگرام!')

def help_command(update, context):
    """واکنش به دستور /help"""
    update.message.reply_text('این ربات برای تست است. از دستور /start برای شروع استفاده کنید.')

def echo(update, context):
    """پاسخ به پیام‌های غیر دستوری"""
    update.message.reply_text(f'پیام شما: {update.message.text}')

def main():
    """شروع ربات"""
    # دریافت توکن از متغیرهای محیطی
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("توکن تلگرام یافت نشد. لطفاً متغیر محیطی TELEGRAM_BOT_TOKEN را تنظیم کنید.")
        return

    # ایجاد آپدیتر
    updater = Updater(token)

    # دریافت دیسپچر برای ثبت هندلرها
    dispatcher = updater.dispatcher

    # ثبت هندلرهای مختلف
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))

    # شروع ربات
    updater.start_polling()
    logger.info("ربات با موفقیت شروع به کار کرد.")
    
    # ادامه اجرا تا زمانی که فشردن Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()