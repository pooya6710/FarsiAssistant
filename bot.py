import asyncio
import logging
import json
import os
from dotenv import load_dotenv
from jdatetime import date as JalaliDate
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters, ConversationHandler
import nest_asyncio

# بارگذاری متغیرهای محیطی از فایل .env
load_dotenv()

# فعال کردن nest_asyncio برای اجازه دادن به حلقه‌های رویداد تودرتو
nest_asyncio.apply()

# فعال کردن لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# دیکشنری برای ذخیره اطلاعات دانشجویان - نگاشت user_id به feeding_code
students = {}

# دیکشنری برای ذخیره منوی هفتگی
menu_data = {
    "saturday": {"breakfast": "تخم مرغ", "lunch": "چلوکباب", "dinner": "سوپ"},
    "sunday": {"breakfast": "پنیر و گردو", "lunch": "خورشت قورمه سبزی", "dinner": "ماکارونی"},
    "monday": {"breakfast": "املت", "lunch": "چلو مرغ", "dinner": "کتلت"},
    "tuesday": {"breakfast": "عدسی", "lunch": "خورشت قیمه", "dinner": "کوکو سبزی"},
    "wednesday": {"breakfast": "کره و مربا", "lunch": "آبگوشت", "dinner": "پیتزا"},
    "thursday": {"breakfast": "نان و پنیر", "lunch": "چلو ماهی", "dinner": "سوپ"},
    "friday": {"breakfast": "حلوا ارده", "lunch": "خورشت فسنجان", "dinner": "ساندویچ"}
}

# فایل برای ذخیره رزروها
RESERVATION_FILE = "reservations.json"

# نگاشت روزهای فارسی
persian_days = {
    "saturday": "شنبه",
    "sunday": "یکشنبه",
    "monday": "دوشنبه",
    "tuesday": "سه‌شنبه",
    "wednesday": "چهارشنبه",
    "thursday": "پنج‌شنبه",
    "friday": "جمعه"
}

# نگاشت وعده‌های غذایی فارسی
persian_meals = {
    "breakfast": "صبحانه",
    "lunch": "ناهار",
    "dinner": "شام"
}

# لیست شناسه چت مدیران - افرادی که می‌توانند تحویل غذا را تایید کنند
OWNER_CHAT_IDS = [286420965]  # با شناسه‌های چت واقعی مدیران جایگزین کنید

# وضعیت‌ها برای مدیریت مکالمه
FEEDING_CODE = 0

# بارگذاری رزروها از فایل
def load_reservations():
    try:
        with open(RESERVATION_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            # تبدیل کلیدهای فارسی به انگلیسی برای استفاده داخلی
            converted_data = {}
            for feeding_code, days in data.items():
                english_days_data = {}
                persian_to_english_days = {v: k for k, v in persian_days.items()}
                persian_to_english_meals = {v: k for k, v in persian_meals.items()}
                
                for day, meals in days.items():
                    english_day = persian_to_english_days.get(day, day)
                    english_meals_data = {persian_to_english_meals.get(meal, meal): name for meal, name in meals.items()}
                    english_days_data[english_day] = english_meals_data
                
                converted_data[feeding_code] = english_days_data
            
            return converted_data
    except (FileNotFoundError, json.JSONDecodeError):
        # اگر فایل وجود نداشت یا نامعتبر بود، دیکشنری خالی برگردان
        return {}

# ذخیره رزروها در فایل
def save_reservations(reservations):
    # تبدیل کلیدهای انگلیسی به فارسی قبل از ذخیره
    persian_reservations = {}
    for feeding_code, days in reservations.items():
        persian_days_data = {}
        for day, meals in days.items():
            persian_day = persian_days.get(day, day)
            persian_meals_data = {persian_meals.get(meal, meal): value for meal, value in meals.items()}
            persian_days_data[persian_day] = persian_meals_data
        persian_reservations[feeding_code] = persian_days_data

    with open(RESERVATION_FILE, "w", encoding="utf-8") as file:
        json.dump(persian_reservations, file, ensure_ascii=False, indent=4)

# بررسی اینکه آیا کاربر مدیر است یا خیر
def is_owner(chat_id):
    return chat_id in OWNER_CHAT_IDS

# مقداردهی اولیه رزروها
reservations = load_reservations()

# تابع‌های پردازش دستورها
def start(update: Update, context: CallbackContext) -> None:
    """شروع کار با ربات و نمایش منوی اصلی"""
    # تنظیم دستورهای ربات برای تجربه کاربری بهتر
    commands = [
        BotCommand("start", "شروع کار با ربات"),
        BotCommand("menu", "مشاهده منوی غذا"),
        BotCommand("register", "ثبت کد تغذیه"),
        BotCommand("reservations", "مشاهده رزروها"),
        BotCommand("help", "راهنما")
    ]
    
    context.bot.set_my_commands(commands)
    
    # نمایش پیام خوش‌آمدگویی و منوی اصلی
    main_menu(update, context)

def main_menu(update: Update, context: CallbackContext) -> None:
    """نمایش منوی اصلی با تمام گزینه‌های موجود"""
    menu_keyboard = [
        [InlineKeyboardButton("\U0001F4D6 مشاهده منو", callback_data="view_menu")],
        [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
        [InlineKeyboardButton("\U0001F4C5 مشاهده رزروها", callback_data="show_reservations")],
        [InlineKeyboardButton("\U0001F4DA راهنما", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(menu_keyboard)
    welcome_message = (
        "\U0001F44B خوش آمدید به سامانه رزرو غذای دانشگاه!\n"
        "\U0001F4D1 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:\n"
    )
    
    # پردازش هر دو حالت پیام و کالبک کوئری
    if update.message:
        update.message.reply_text(welcome_message, reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup)

def help_command(update: Update, context: CallbackContext) -> None:
    """نمایش اطلاعات راهنما"""
    help_text = (
        "\U0001F4DA <b>راهنمای سامانه رزرو غذا:</b>\n\n"
        "\U0001F539 <b>مشاهده منو:</b> برای دیدن منوی غذایی هفته\n"
        "\U0001F539 <b>ثبت کد تغذیه:</b> برای ثبت یا تغییر کد تغذیه خود\n"
        "\U0001F539 <b>مشاهده رزروها:</b> برای دیدن رزروهای فعلی خود\n\n"
        "\U0001F4CC برای رزرو غذا، ابتدا باید کد تغذیه خود را ثبت کنید، سپس از منوی غذایی، وعده‌های مورد نظر را انتخاب نمایید.\n"
        "\U0001F4CC هر رزرو به کد تغذیه شما مرتبط می‌شود و در هنگام تحویل غذا، کد تغذیه شما مورد بررسی قرار می‌گیرد.\n"
    )
    
    back_button = [[InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(back_button)
    
    if update.message:
        update.message.reply_text(help_text, parse_mode="HTML", reply_markup=reply_markup)
    elif update.callback_query:
        update.callback_query.edit_message_text(help_text, parse_mode="HTML", reply_markup=reply_markup)

def register_command(update: Update, context: CallbackContext) -> int:
    """شروع فرآیند ثبت کد تغذیه"""
    update.message.reply_text(
        "\U0001F4DD لطفاً کد تغذیه خود را ارسال کنید:"
    )
    return FEEDING_CODE

def process_feeding_code(update: Update, context: CallbackContext) -> int:
    """پردازش کد تغذیه وارد شده توسط کاربر"""
    code = update.message.text.strip()
    
    if code.isdigit():
        student_id = str(update.effective_user.id)
        students[student_id] = code
        if code not in reservations:
            reservations[code] = {}
        save_reservations(reservations)
        
        update.message.reply_text(
            f"\U00002705 کد تغذیه شما ({code}) با موفقیت ثبت شد!\n"
            "\U0001F4D1 بازگشت به منوی اصلی:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
            ])
        )
        return ConversationHandler.END
    else:
        update.message.reply_text(
            "\U0001F6AB کد تغذیه باید فقط شامل اعداد باشد. لطفاً دوباره تلاش کنید."
        )
        return FEEDING_CODE

def cancel(update: Update, context: CallbackContext) -> int:
    """لغو مکالمه"""
    update.message.reply_text(
        "\U0001F6AB عملیات لغو شد. بازگشت به منوی اصلی...",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
        ])
    )
    return ConversationHandler.END

def view_menu(update: Update, context: CallbackContext) -> None:
    """نمایش منوی هفتگی با دکمه‌های انتخاب روز"""
    days_keyboard = [
        [InlineKeyboardButton(f"\U0001F4C6 {persian_days[day]}", callback_data=f"day_{day}")] 
        for day in menu_data.keys()
    ]
    days_keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(days_keyboard)
    
    if update.callback_query:
        update.callback_query.edit_message_text(
            "\U0001F4D6 لطفاً روز مورد نظر خود را انتخاب کنید:", 
            reply_markup=reply_markup
        )
    else:
        update.message.reply_text(
            "\U0001F4D6 لطفاً روز مورد نظر خود را انتخاب کنید:", 
            reply_markup=reply_markup
        )

def show_reservations(update: Update, context: CallbackContext) -> None:
    """نمایش رزروهای فعلی کاربر"""
    user_id = str(update.effective_user.id)
    
    if user_id not in students:
        message = "\U0001F6AB شما هنوز کد تغذیه خود را ثبت نکرده‌اید. لطفاً ابتدا کد تغذیه خود را ثبت کنید."
        keyboard = [[InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")]]
    else:
        feeding_code = students[user_id]
        
        if feeding_code not in reservations or not reservations[feeding_code]:
            message = "\U0001F4C5 شما هیچ رزروی ندارید. لطفاً از منوی غذا، وعده‌های مورد نظر خود را رزرو کنید."
            keyboard = [[InlineKeyboardButton("\U0001F4D6 مشاهده منو", callback_data="view_menu")]]
        else:
            message = f"<b>\U0001F4C5 رزروهای شما با کد تغذیه {feeding_code}:</b>\n\n"
            user_reservations = reservations[feeding_code]
            
            for day, meals in user_reservations.items():
                persian_day = persian_days.get(day, day)
                message += f"<b>\U0001F4C6 روز {persian_day}:</b>\n"
                for meal, food in meals.items():
                    persian_meal = persian_meals.get(meal, meal)
                    message += f"  \U0001F374 {persian_meal}: {food}\n"
                message += "\n"
                
            keyboard = []
    
    keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        update.callback_query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)
    else:
        update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)

def handle_callback(update: Update, context: CallbackContext) -> None:
    """پردازش کالبک کوئری‌ها از کیبوردهای درون خطی"""
    query = update.callback_query
    query.answer()  # پاسخ به کالبک کوئری برای توقف نشانگر بارگذاری
    
    if query.data == "back_to_menu":
        main_menu(update, context)
        return
    
    elif query.data == "view_menu":
        view_menu(update, context)
        return
    
    elif query.data == "register":
        query.edit_message_text(
            "\U0001F4DD لطفاً کد تغذیه خود را ارسال کنید:\n\n"
            "برای ثبت کد تغذیه از دستور /register استفاده کنید."
        )
        return
    
    elif query.data == "show_reservations":
        show_reservations(update, context)
        return
    
    elif query.data == "help":
        help_command(update, context)
        return
    
    # پردازش انتخاب روز
    elif query.data.startswith("day_"):
        selected_day = query.data.split("_")[1]
        context.user_data['selected_day'] = selected_day
        
        meals = menu_data[selected_day]
        meals_keyboard = [
            [InlineKeyboardButton(f"\U0001F374 صبحانه: {meals['breakfast']}", callback_data=f"meal_{selected_day}_breakfast")],
            [InlineKeyboardButton(f"\U0001F35C ناهار: {meals['lunch']}", callback_data=f"meal_{selected_day}_lunch")],
            [InlineKeyboardButton(f"\U0001F35D شام: {meals['dinner']}", callback_data=f"meal_{selected_day}_dinner")],
            [InlineKeyboardButton("\U0001F4E6 رزرو تمام وعده‌ها", callback_data=f"meal_{selected_day}_all")],
            [InlineKeyboardButton("\U0001F519 بازگشت به انتخاب روز", callback_data="view_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(meals_keyboard)
        
        query.edit_message_text(
            f"\U0001F4C6 لطفاً وعده مورد نظر خود را برای روز {persian_days[selected_day]} انتخاب کنید:", 
            reply_markup=reply_markup
        )
        return
    
    # پردازش انتخاب وعده غذایی
    elif query.data.startswith("meal_"):
        parts = query.data.split("_")
        selected_day = parts[1]
        selected_meal = parts[2]
        
        # بررسی اینکه آیا کاربر ثبت نام کرده است یا خیر
        user_id = str(update.effective_user.id)
        if user_id not in students:
            query.edit_message_text(
                "\U0001F6AB لطفاً ابتدا کد تغذیه خود را ثبت کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
                    [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
                ])
            )
            return
        
        feeding_code = students[user_id]
        
        # مقداردهی اولیه رزروها برای این کد تغذیه در صورت عدم وجود
        if feeding_code not in reservations:
            reservations[feeding_code] = {}
        
        # مقداردهی اولیه رزروها برای این روز در صورت عدم وجود
        if selected_day not in reservations[feeding_code]:
            reservations[feeding_code][selected_day] = {}
        
        # پردازش رزرو برای تمام وعده‌ها یا یک وعده خاص
        if selected_meal == "all":
            meals = menu_data[selected_day]
            for meal_type, food in meals.items():
                reservations[feeding_code][selected_day][meal_type] = food
            
            message = (
                f"\U00002705 رزرو شما برای تمام وعده‌های روز {persian_days[selected_day]} ثبت شد:\n"
                f"\U0001F374 صبحانه: {meals['breakfast']}\n"
                f"\U0001F35C ناهار: {meals['lunch']}\n"
                f"\U0001F35D شام: {meals['dinner']}\n"
                f"\U0001F4DD کد تغذیه شما: {feeding_code}"
            )
        else:
            food = menu_data[selected_day][selected_meal]
            reservations[feeding_code][selected_day][selected_meal] = food
            
            message = (
                f"\U00002705 رزرو شما برای {persian_meals[selected_meal]} روز {persian_days[selected_day]} ثبت شد:\n"
                f"\U0001F374 {persian_meals[selected_meal]}: {food}\n"
                f"\U0001F4DD کد تغذیه شما: {feeding_code}"
            )
        
        # ذخیره رزروهای به‌روزرسانی شده
        save_reservations(reservations)
        
        # ارائه بازخورد و گزینه‌های ناوبری
        query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F4C5 مشاهده رزروها", callback_data="show_reservations")],
                [InlineKeyboardButton("\U0001F4D6 بازگشت به منو", callback_data="view_menu")],
                [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
            ])
        )
        return
    
    # پردازش تایید تحویل غذا (فقط برای مدیر)
    elif query.data.startswith("confirm_"):
        # بررسی اینکه آیا کاربر مدیر است یا خیر
        if not is_owner(update.effective_user.id):
            query.edit_message_text(
                "\U0001F6AB شما اجازه تایید تحویل غذا را ندارید."
            )
            return
        
        # تجزیه داده‌های تایید
        parts = query.data.split("_")
        feeding_code = parts[1]
        selected_day = parts[2]
        selected_meal = parts[3]
        
        # بررسی اینکه آیا رزرو وجود دارد یا خیر
        if (feeding_code in reservations and 
            selected_day in reservations[feeding_code] and 
            selected_meal in reservations[feeding_code][selected_day]):
            
            # حذف وعده غذایی تحویل داده شده از رزروها
            food = reservations[feeding_code][selected_day][selected_meal]
            del reservations[feeding_code][selected_day][selected_meal]
            
            # اگر روز دیگر وعده‌ای ندارد، روز را حذف کن
            if not reservations[feeding_code][selected_day]:
                del reservations[feeding_code][selected_day]
                
            # اگر کد تغذیه دیگر روزی ندارد، کد تغذیه را حذف کن
            if not reservations[feeding_code]:
                del reservations[feeding_code]
                
            # ذخیره رزروهای به‌روزرسانی شده
            save_reservations(reservations)
            
            # ارائه پیام تایید
            query.edit_message_text(
                f"\U00002705 تحویل {persian_meals[selected_meal]} ({food}) برای کد تغذیه {feeding_code} تایید شد."
            )
        else:
            query.edit_message_text(
                "\U0001F6AB رزرو مورد نظر یافت نشد یا قبلاً تحویل داده شده است."
            )
        return
            
    # پردازش سایر کالبک‌ها
    query.edit_message_text("گزینه نامعتبر است. بازگشت به منوی اصلی...")
    main_menu(update, context)

def menu_command(update: Update, context: CallbackContext) -> None:
    """پردازش دستور /menu"""
    view_menu(update, context)

def reservations_command(update: Update, context: CallbackContext) -> None:
    """پردازش دستور /reservations"""
    show_reservations(update, context)

def message_handler(update: Update, context: CallbackContext) -> None:
    """پردازش پیام‌های متنی خارج از مکالمه‌ها"""
    # مدیر می‌تواند با وارد کردن کد تغذیه رزروها را بررسی کند
    if is_owner(update.effective_user.id):
        code = update.message.text.strip()
        if code.isdigit() and code in reservations:
            message = f"<b>\U0001F4C5 رزروهای کد تغذیه {code}:</b>\n\n"
            
            for day, meals in reservations[code].items():
                persian_day = persian_days.get(day, day)
                message += f"<b>\U0001F4C6 روز {persian_day}:</b>\n"
                
                # ایجاد دکمه‌های تایید برای هر وعده غذایی
                keyboard = []
                for meal, food in meals.items():
                    persian_meal = persian_meals.get(meal, meal)
                    message += f"  \U0001F374 {persian_meal}: {food}\n"
                    keyboard.append([
                        InlineKeyboardButton(
                            f"\U00002705 تایید تحویل {persian_meal}",
                            callback_data=f"confirm_{code}_{day}_{meal}"
                        )
                    ])
                message += "\n"  # افزودن فاصله بین روزها
                
                # ارسال پیام با دکمه‌های تایید
                keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت", callback_data="back_to_menu")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)
                return
        
    # برای کاربران عادی، نمایش پیام راهنما با دستورهای موجود
    update.message.reply_text(
        "برای استفاده از ربات از دستورهای زیر استفاده کنید:\n"
        "/start - شروع کار با ربات\n"
        "/menu - مشاهده منوی غذا\n"
        "/register - ثبت کد تغذیه\n"
        "/reservations - مشاهده رزروها\n"
        "/help - راهنما",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
        ])
    )

def main() -> None:
    """شروع ربات."""
    # دریافت توکن ربات از متغیرهای محیطی
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("توکن ربات تلگرام مشخص نشده است. لطفاً در فایل .env آن را تنظیم کنید.")
        return
    
    # ایجاد Updater
    updater = Updater(token)
    
    # دریافت دسترسی به dispatcher
    dp = updater.dispatcher

    # اضافه کردن مدیریت‌کننده مکالمه برای ثبت نام
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("register", register_command)],
        states={
            FEEDING_CODE: [MessageHandler(Filters.text & ~Filters.command, process_feeding_code)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # اضافه کردن مدیریت‌کننده‌ها
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("menu", menu_command))
    dp.add_handler(CommandHandler("reservations", reservations_command))
    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(handle_callback))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))

    # شروع ربات
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()