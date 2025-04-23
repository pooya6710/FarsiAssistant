import asyncio
import logging
import json
import os
import datetime
import subprocess
from dotenv import load_dotenv
from jdatetime import date as JalaliDate
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters, ConversationHandler
import nest_asyncio
from models import init_db, Student, Reservation, Menu, DatabaseBackup, load_default_menu, migrate_from_json_to_db

# بارگذاری متغیرهای محیطی از فایل .env
load_dotenv()

# فعال کردن nest_asyncio برای اجازه دادن به حلقه‌های رویداد تودرتو
nest_asyncio.apply()

# فعال کردن لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# فایل قبلی رزروها (برای مهاجرت)
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
EDIT_MENU_DAY = 1
EDIT_MENU_MEAL = 2
EDIT_MENU_FOOD = 3
DATABASE_BACKUP_DESC = 4

# ایجاد اتصال به دیتابیس
db_session = init_db()

# بارگذاری منوی پیش‌فرض به دیتابیس
load_default_menu(db_session)

# مهاجرت داده‌ها از فایل JSON به دیتابیس (اگر فایل وجود داشته باشد)
migrate_from_json_to_db(RESERVATION_FILE, db_session)

# دیکشنری موقت برای کش کردن کد تغذیه‌ها (شناسه کاربری به کد تغذیه)
students = {}

# بارگذاری دانشجویان از دیتابیس به کش
def load_students_to_cache():
    all_students = db_session.query(Student).all()
    for student in all_students:
        students[student.user_id] = student.feeding_code

# بارگذاری دانشجویان به کش در شروع کار
load_students_to_cache()

# بارگذاری منوی غذا از دیتابیس
def get_menu_data():
    menu_items = db_session.query(Menu).all()
    menu_data = {}
    for item in menu_items:
        menu_data[item.day] = item.meal_data
    return menu_data

# دریافت منوی غذا
menu_data = get_menu_data()

# بررسی اینکه آیا کاربر مدیر است یا خیر
def is_owner(chat_id):
    return chat_id in OWNER_CHAT_IDS

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
    
    # اضافه کردن منوی مدیریت برای مدیران سیستم
    chat_id = update.effective_chat.id
    if is_owner(chat_id):
        menu_keyboard.append([
            InlineKeyboardButton("\U0001F680 پنل مدیریت", callback_data="admin_panel")
        ])
    
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
        user_id = str(update.effective_user.id)
        
        # بررسی اینکه آیا دانشجو قبلاً در دیتابیس وجود دارد
        student = db_session.query(Student).filter_by(user_id=user_id).first()
        
        if student:
            # به‌روزرسانی کد تغذیه دانشجو
            student.feeding_code = code
        else:
            # ایجاد دانشجوی جدید
            student = Student(user_id=user_id, feeding_code=code)
            db_session.add(student)
        
        db_session.commit()
        
        # به‌روزرسانی کش
        students[user_id] = code
        
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
        
        # دریافت دانشجو از دیتابیس
        student = db_session.query(Student).filter_by(feeding_code=feeding_code).first()
        
        if not student:
            message = "\U0001F6AB خطا در بازیابی اطلاعات شما. لطفاً دوباره کد تغذیه خود را ثبت کنید."
            keyboard = [[InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")]]
        else:
            # دریافت رزروهای دانشجو از دیتابیس
            reservations = db_session.query(Reservation).filter_by(student_id=student.id).all()
            
            if not reservations:
                message = "\U0001F4C5 شما هیچ رزروی ندارید. لطفاً از منوی غذا، وعده‌های مورد نظر خود را رزرو کنید."
                keyboard = [[InlineKeyboardButton("\U0001F4D6 مشاهده منو", callback_data="view_menu")]]
            else:
                message = f"<b>\U0001F4C5 رزروهای شما با کد تغذیه {feeding_code}:</b>\n\n"
                
                # گروه‌بندی رزروها بر اساس روز
                reservations_by_day = {}
                for reservation in reservations:
                    if reservation.day not in reservations_by_day:
                        reservations_by_day[reservation.day] = []
                    reservations_by_day[reservation.day].append(reservation)
                
                # نمایش رزروها به صورت گروه‌بندی شده بر اساس روز
                for day, day_reservations in reservations_by_day.items():
                    persian_day = persian_days.get(day, day)
                    message += f"<b>\U0001F4C6 روز {persian_day}:</b>\n"
                    
                    for reservation in day_reservations:
                        persian_meal = persian_meals.get(reservation.meal_type, reservation.meal_type)
                        message += f"  \U0001F374 {persian_meal}: {reservation.food}\n"
                    
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
        
        # پیدا کردن دانشجو در دیتابیس
        student = db_session.query(Student).filter_by(feeding_code=feeding_code).first()
        
        if not student:
            query.edit_message_text(
                "\U0001F6AB خطا در بازیابی اطلاعات شما. لطفاً دوباره کد تغذیه خود را ثبت کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
                    [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
                ])
            )
            return
        
        # پردازش رزرو برای تمام وعده‌ها یا یک وعده خاص
        if selected_meal == "all":
            meals = menu_data[selected_day]
            message_parts = []
            
            for meal_type, food in meals.items():
                # حذف رزرو قبلی اگر وجود داشته باشد
                db_session.query(Reservation).filter_by(
                    student_id=student.id,
                    day=selected_day,
                    meal_type=meal_type
                ).delete()
                
                # ایجاد رزرو جدید
                reservation = Reservation(
                    student_id=student.id,
                    day=selected_day,
                    meal_type=meal_type,
                    food=food
                )
                db_session.add(reservation)
                
                persian_meal = persian_meals.get(meal_type, meal_type)
                message_parts.append(f"\U0001F374 {persian_meal}: {food}")
            
            db_session.commit()
            
            message = (
                f"\U00002705 رزرو شما برای تمام وعده‌های روز {persian_days[selected_day]} ثبت شد:\n"
                + "\n".join(message_parts) + 
                f"\n\U0001F4DD کد تغذیه شما: {feeding_code}"
            )
        else:
            food = menu_data[selected_day][selected_meal]
            
            # حذف رزرو قبلی اگر وجود داشته باشد
            db_session.query(Reservation).filter_by(
                student_id=student.id,
                day=selected_day,
                meal_type=selected_meal
            ).delete()
            
            # ایجاد رزرو جدید
            reservation = Reservation(
                student_id=student.id,
                day=selected_day,
                meal_type=selected_meal,
                food=food
            )
            db_session.add(reservation)
            db_session.commit()
            
            message = (
                f"\U00002705 رزرو شما برای {persian_meals[selected_meal]} روز {persian_days[selected_day]} ثبت شد:\n"
                f"\U0001F374 {persian_meals[selected_meal]}: {food}\n"
                f"\U0001F4DD کد تغذیه شما: {feeding_code}"
            )
        
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
        reservation_id = int(parts[1])  # شناسه رزرو
        
        # پیدا کردن رزرو در دیتابیس
        reservation = db_session.query(Reservation).filter_by(id=reservation_id).first()
        
        if reservation:
            # دریافت اطلاعات رزرو قبل از حذف
            student = db_session.query(Student).filter_by(id=reservation.student_id).first()
            day = persian_days.get(reservation.day, reservation.day)
            meal = persian_meals.get(reservation.meal_type, reservation.meal_type)
            food = reservation.food
            
            # حذف رزرو از دیتابیس
            db_session.delete(reservation)
            db_session.commit()
            
            # ارائه پیام تایید
            query.edit_message_text(
                f"\U00002705 تحویل {meal} ({food}) برای کد تغذیه {student.feeding_code} در روز {day} تایید شد."
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
        if code.isdigit():
            # پیدا کردن دانشجو با کد تغذیه وارد شده
            student = db_session.query(Student).filter_by(feeding_code=code).first()
            
            if student:
                # دریافت رزروهای دانشجو
                reservations = db_session.query(Reservation).filter_by(student_id=student.id).all()
                
                if reservations:
                    message = f"<b>\U0001F4C5 رزروهای کد تغذیه {code}:</b>\n\n"
                    
                    # گروه‌بندی رزروها بر اساس روز
                    reservations_by_day = {}
                    for reservation in reservations:
                        if reservation.day not in reservations_by_day:
                            reservations_by_day[reservation.day] = []
                        reservations_by_day[reservation.day].append(reservation)
                    
                    # ایجاد دکمه‌های تایید برای هر رزرو
                    for day, day_reservations in reservations_by_day.items():
                        persian_day = persian_days.get(day, day)
                        message += f"<b>\U0001F4C6 روز {persian_day}:</b>\n"
                        
                        keyboard = []
                        for reservation in day_reservations:
                            persian_meal = persian_meals.get(reservation.meal_type, reservation.meal_type)
                            message += f"  \U0001F374 {persian_meal}: {reservation.food}\n"
                            keyboard.append([
                                InlineKeyboardButton(
                                    f"\U00002705 تایید تحویل {persian_meal}",
                                    callback_data=f"confirm_{reservation.id}"
                                )
                            ])
                        
                        message += "\n"
                        
                        # ارسال پیام با دکمه‌های تایید
                        keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت", callback_data="back_to_menu")])
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)
                        return
                else:
                    update.message.reply_text(f"\U0001F6AB رزروی برای کد تغذیه {code} یافت نشد.")
                    return
            else:
                update.message.reply_text(f"\U0001F6AB دانشجویی با کد تغذیه {code} یافت نشد.")
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