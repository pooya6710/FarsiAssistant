import asyncio
import logging
import json
import os
import datetime
from dotenv import load_dotenv
from jdatetime import date as JalaliDate
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
import nest_asyncio
from models import init_db, Student, Reservation, Menu, DatabaseBackup, load_default_menu, migrate_from_json_to_db
from sqlalchemy import text

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
# دریافت شناسه‌های مدیران از متغیرهای محیطی یا مقدار پیش‌فرض
admin_ids_str = os.environ.get("ADMIN_CHAT_IDS", "286420965")
OWNER_CHAT_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]

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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """شروع کار با ربات و نمایش منوی اصلی"""
    # تنظیم دستورهای ربات برای تجربه کاربری بهتر
    commands = [
        BotCommand("start", "شروع کار با ربات"),
        BotCommand("menu", "مشاهده منوی غذا"),
        BotCommand("register", "ثبت کد تغذیه"),
        BotCommand("reservations", "مشاهده رزروها"),
        BotCommand("help", "راهنما")
    ]
    
    await context.bot.set_my_commands(commands)
    
    # نمایش پیام خوش‌آمدگویی و منوی اصلی
    await main_menu(update, context)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_message, reply_markup=reply_markup)

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

def admin_panel(update: Update, context: CallbackContext) -> None:
    """نمایش پنل مدیریت برای مدیران سیستم"""
    chat_id = update.effective_chat.id
    
    # بررسی دسترسی
    if not is_owner(chat_id):
        if update.callback_query:
            update.callback_query.edit_message_text("\U0001F6AB شما دسترسی کافی برای استفاده از پنل مدیریت را ندارید.")
        else:
            update.message.reply_text("\U0001F6AB شما دسترسی کافی برای استفاده از پنل مدیریت را ندارید.")
        return
    
    # ایجاد دکمه‌های پنل مدیریت
    admin_keyboard = [
        [InlineKeyboardButton("\U0001F4DD مدیریت منوی غذا", callback_data="admin_menu")],
        [InlineKeyboardButton("\U0001F465 مشاهده لیست کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("\U0001F4E5 تهیه نسخه پشتیبان", callback_data="admin_backup")],
        [InlineKeyboardButton("\U0001F4C3 مدیریت رزروها و تحویل غذا", callback_data="admin_delivery")],
        [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(admin_keyboard)
    
    # نمایش پنل مدیریت
    admin_text = (
        "\U0001F680 <b>پنل مدیریت سامانه رزرو غذا</b>\n\n"
        "\U00002728 به پنل مدیریت سامانه رزرو غذای دانشگاه خوش آمدید.\n"
        "\U0001F4DD لطفاً گزینه مورد نظر خود را انتخاب کنید:\n"
    )
    
    if update.callback_query:
        update.callback_query.edit_message_text(admin_text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        update.message.reply_text(admin_text, parse_mode="HTML", reply_markup=reply_markup)

def admin_menu_management(update: Update, context: CallbackContext) -> None:
    """مدیریت منوی غذای هفتگی"""
    # نمایش روزهای هفته برای ویرایش منو
    days_keyboard = [
        [InlineKeyboardButton(f"\U0001F4C6 {persian_days[day]}", callback_data=f"edit_menu_{day}")] 
        for day in menu_data.keys()
    ]
    days_keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(days_keyboard)
    
    admin_menu_text = (
        "\U0001F4DD <b>مدیریت منوی هفتگی</b>\n\n"
        "\U0001F4C6 لطفاً روز مورد نظر برای ویرایش منو را انتخاب کنید:"
    )
    
    update.callback_query.edit_message_text(admin_menu_text, parse_mode="HTML", reply_markup=reply_markup)

def admin_users_list(update: Update, context: CallbackContext) -> None:
    """نمایش لیست کاربران ثبت‌نام شده"""
    # دریافت لیست دانشجویان از دیتابیس
    all_students = db_session.query(Student).all()
    
    if not all_students:
        update.callback_query.edit_message_text(
            "\U0001F6AB هیچ کاربری در سیستم ثبت‌نام نشده است.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
            ])
        )
        return
    
    # تهیه متن لیست کاربران
    users_text = "\U0001F465 <b>لیست کاربران ثبت‌نام شده:</b>\n\n"
    
    for i, student in enumerate(all_students, 1):
        reg_date = student.registration_date.strftime("%Y-%m-%d") if student.registration_date else "نامشخص"
        users_text += f"{i}. کد تغذیه: <code>{student.feeding_code}</code>\n"
        users_text += f"   شناسه کاربری: <code>{student.user_id}</code>\n"
        users_text += f"   تاریخ ثبت‌نام: {reg_date}\n"
        users_text += f"   تلفن: {student.phone or 'ثبت نشده'}\n\n"
    
    # در صورتی که متن خیلی طولانی باشد، آن را به چند بخش تقسیم می‌کنیم
    if len(users_text) > 4000:
        chunks = [users_text[i:i+4000] for i in range(0, len(users_text), 4000)]
        update.callback_query.edit_message_text(
            chunks[0] + "\n\n(ادامه دارد...)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
            ])
        )
        
        # ارسال بقیه بخش‌ها به صورت پیام‌های جداگانه
        for chunk in chunks[1:]:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=chunk,
                parse_mode="HTML"
            )
    else:
        update.callback_query.edit_message_text(
            users_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
            ])
        )

def admin_backup_database(update: Update, context: CallbackContext) -> None:
    """تهیه نسخه پشتیبان از دیتابیس"""
    # نمایش فرم تهیه نسخه پشتیبان
    backup_text = (
        "\U0001F4E5 <b>تهیه نسخه پشتیبان از دیتابیس</b>\n\n"
        "\U0001F4DD لطفاً توضیحات مختصری برای این نسخه پشتیبان وارد کنید:\n"
        "(برای مثال: «پشتیبان‌گیری هفتگی» یا «قبل از به‌روزرسانی سیستم»)"
    )
    
    update.callback_query.edit_message_text(
        backup_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
        ])
    )
    
    # تنظیم مرحله بعدی مکالمه
    return DATABASE_BACKUP_DESC

def create_database_backup(description, chat_id, context: CallbackContext) -> None:
    """ایجاد فایل پشتیبان از دیتابیس"""
    try:
        # ایجاد نام فایل بر اساس تاریخ و زمان
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.sql"
        
        # دریافت مسیر فایل پشتیبان
        backup_path = os.path.join(os.getcwd(), filename)
        
        # اجرای دستور pg_dump برای تهیه نسخه پشتیبان
        database_url = os.environ.get('DATABASE_URL')
        # جدا کردن اطلاعات اتصال از DATABASE_URL
        db_info = {
            'host': os.environ.get('PGHOST'),
            'port': os.environ.get('PGPORT'),
            'database': os.environ.get('PGDATABASE'),
            'user': os.environ.get('PGUSER'),
            'password': os.environ.get('PGPASSWORD')
        }
        
        # ساخت دستور pg_dump
        dump_command = [
            'pg_dump',
            '-h', db_info['host'],
            '-p', db_info['port'],
            '-U', db_info['user'],
            '-d', db_info['database'],
            '-f', backup_path
        ]
        
        # تنظیم متغیر محیطی PGPASSWORD برای pg_dump
        env = os.environ.copy()
        env['PGPASSWORD'] = db_info['password']
        
        # اجرای دستور pg_dump
        subprocess.run(dump_command, env=env, check=True)
        
        # بررسی اندازه فایل
        file_size = os.path.getsize(backup_path)
        
        # ثبت اطلاعات پشتیبان‌گیری در دیتابیس
        backup = DatabaseBackup(
            filename=filename,
            description=description,
            size=file_size
        )
        db_session.add(backup)
        db_session.commit()
        
        # ارسال پیام موفقیت
        context.bot.send_message(
            chat_id=chat_id,
            text=f"\U00002705 <b>نسخه پشتیبان با موفقیت ایجاد شد!</b>\n\n"
                 f"\U0001F4C1 نام فایل: {filename}\n"
                 f"\U0001F4C4 اندازه فایل: {file_size / 1024:.1f} کیلوبایت\n"
                 f"\U0001F4DD توضیحات: {description}",
            parse_mode="HTML"
        )
        
        # ارسال فایل پشتیبان به کاربر
        with open(backup_path, 'rb') as backup_file:
            context.bot.send_document(
                chat_id=chat_id,
                document=backup_file,
                filename=filename,
                caption=f"\U0001F4E5 فایل پشتیبان دیتابیس - {description}"
            )
        
        # حذف فایل موقت
        os.remove(backup_path)
        
    except Exception as e:
        context.bot.send_message(
            chat_id=chat_id,
            text=f"\U0001F6AB <b>خطا در تهیه نسخه پشتیبان:</b>\n\n{str(e)}",
            parse_mode="HTML"
        )

def admin_delivery_management(update: Update, context: CallbackContext) -> None:
    """مدیریت تحویل غذا و مشاهده رزروها"""
    # دریافت لیست رزروها از دیتابیس
    all_reservations = db_session.query(Reservation, Student).join(Student).all()
    
    if not all_reservations:
        update.callback_query.edit_message_text(
            "\U0001F6AB هیچ رزروی در سیستم ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
            ])
        )
        return
    
    # گروه‌بندی رزروها بر اساس روزها
    reservations_by_day = {}
    for reservation, student in all_reservations:
        day = reservation.day
        if day not in reservations_by_day:
            reservations_by_day[day] = []
        reservations_by_day[day].append((reservation, student))
    
    # ایجاد دکمه‌های انتخاب روز برای مشاهده رزروها
    days_keyboard = [
        [InlineKeyboardButton(f"\U0001F4C6 {persian_days[day]} ({len(reservations)})", callback_data=f"delivery_day_{day}")] 
        for day, reservations in reservations_by_day.items()
    ]
    days_keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(days_keyboard)
    
    delivery_text = (
        "\U0001F4C3 <b>مدیریت رزروها و تحویل غذا</b>\n\n"
        "\U0001F4C6 لطفاً روز مورد نظر برای مشاهده رزروها و مدیریت تحویل غذا را انتخاب کنید:"
    )
    
    update.callback_query.edit_message_text(delivery_text, parse_mode="HTML", reply_markup=reply_markup)

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
        
    # پردازش دکمه‌های پنل مدیریت
    elif query.data == "admin_panel":
        admin_panel(update, context)
        return
        
    elif query.data == "admin_menu":
        admin_menu_management(update, context)
        return
        
    elif query.data == "admin_users":
        admin_users_list(update, context)
        return
        
    elif query.data == "admin_backup":
        return admin_backup_database(update, context)
        
    elif query.data == "admin_delivery":
        admin_delivery_management(update, context)
        return
        
    # پردازش دکمه‌های ویرایش منوی غذا
    elif query.data.startswith("edit_menu_"):
        selected_day = query.data.split("_")[2]
        # ذخیره روز انتخابی در داده‌های کاربر
        context.user_data['edit_day'] = selected_day
        
        # نمایش وعده‌های غذایی روز انتخابی
        meals = menu_data[selected_day]
        meals_keyboard = [
            [InlineKeyboardButton(f"\U0001F374 صبحانه: {meals['breakfast']}", callback_data=f"edit_meal_{selected_day}_breakfast")],
            [InlineKeyboardButton(f"\U0001F35C ناهار: {meals['lunch']}", callback_data=f"edit_meal_{selected_day}_lunch")],
            [InlineKeyboardButton(f"\U0001F35D شام: {meals['dinner']}", callback_data=f"edit_meal_{selected_day}_dinner")],
            [InlineKeyboardButton("\U0001F519 بازگشت به انتخاب روز", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(meals_keyboard)
        
        # نمایش پیام
        query.edit_message_text(
            f"\U0001F4DD <b>ویرایش منوی {persian_days[selected_day]}</b>\n\n"
            "\U0001F374 لطفاً وعده غذایی مورد نظر برای ویرایش را انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        return
        
    # پردازش انتخاب وعده غذایی برای ویرایش
    elif query.data.startswith("edit_meal_"):
        parts = query.data.split("_")
        selected_day = parts[2]
        selected_meal = parts[3]
        
        # ذخیره اطلاعات در داده‌های کاربر
        context.user_data['edit_day'] = selected_day
        context.user_data['edit_meal'] = selected_meal
        
        # نمایش فرم ویرایش
        current_food = menu_data[selected_day][selected_meal]
        persian_meal = persian_meals[selected_meal]
        
        query.edit_message_text(
            f"\U0001F4DD <b>ویرایش {persian_meal} روز {persian_days[selected_day]}</b>\n\n"
            f"\U0001F374 غذای فعلی: {current_food}\n\n"
            "\U0001F4DD لطفاً نام غذای جدید را وارد کنید.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت", callback_data=f"edit_menu_{selected_day}")]
            ])
        )
        
        # تنظیم مرحله بعدی مکالمه
        return EDIT_MENU_FOOD
        
    # پردازش دکمه‌های مدیریت تحویل غذا
    elif query.data.startswith("delivery_day_"):
        selected_day = query.data.split("_")[2]
        
        # دریافت رزروهای روز انتخابی
        reservations_query = db_session.query(Reservation, Student).join(Student).filter(Reservation.day == selected_day)
        day_reservations = reservations_query.all()
        
        if not day_reservations:
            query.edit_message_text(
                f"\U0001F6AB هیچ رزروی برای روز {persian_days[selected_day]} ثبت نشده است.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت به مدیریت تحویل", callback_data="admin_delivery")]
                ])
            )
            return
        
        # گروه‌بندی رزروها بر اساس وعده غذایی
        reservations_by_meal = {
            'breakfast': [],
            'lunch': [],
            'dinner': []
        }
        
        for reservation, student in day_reservations:
            reservations_by_meal[reservation.meal_type].append((reservation, student))
        
        # تهیه متن لیست رزروها
        text = f"\U0001F4C3 <b>لیست رزروهای روز {persian_days[selected_day]}</b>\n\n"
        
        for meal_type, meal_reservations in reservations_by_meal.items():
            if meal_reservations:
                text += f"\U0001F374 <b>{persian_meals[meal_type]}:</b>\n"
                for i, (reservation, student) in enumerate(meal_reservations, 1):
                    delivered = "\U00002705" if reservation.is_delivered else "\U0001F551"
                    text += f"{i}. کد تغذیه: <code>{student.feeding_code}</code> - غذا: {reservation.food} {delivered}\n"
                text += "\n"
        
        # ایجاد دکمه‌های مدیریت تحویل غذا
        keyboard = []
        
        for meal_type, meal_reservations in reservations_by_meal.items():
            if meal_reservations:
                keyboard.append([
                    InlineKeyboardButton(
                        f"\U0001F374 مدیریت {persian_meals[meal_type]} ({len(meal_reservations)})", 
                        callback_data=f"manage_meal_{selected_day}_{meal_type}"
                    )
                ])
        
        keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت به انتخاب روز", callback_data="admin_delivery")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
        return
        
    # پردازش مدیریت تحویل وعده غذایی خاص
    elif query.data.startswith("manage_meal_"):
        parts = query.data.split("_")
        selected_day = parts[2]
        selected_meal = parts[3]
        
        # دریافت رزروهای وعده انتخابی
        reservations_query = db_session.query(Reservation, Student).join(Student).filter(
            Reservation.day == selected_day,
            Reservation.meal_type == selected_meal
        )
        meal_reservations = reservations_query.all()
        
        # تهیه متن و دکمه‌های مدیریت تحویل
        text = f"\U0001F4C3 <b>مدیریت تحویل {persian_meals[selected_meal]} روز {persian_days[selected_day]}</b>\n\n"
        
        keyboard = []
        for reservation, student in meal_reservations:
            delivered_status = "✅ تحویل شده" if reservation.is_delivered else "❌ تحویل نشده"
            keyboard.append([
                InlineKeyboardButton(
                    f"کد: {student.feeding_code} - {reservation.food} - {delivered_status}",
                    callback_data=f"toggle_delivered_{reservation.id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت", callback_data=f"delivery_day_{selected_day}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
        return
        
    # پردازش تغییر وضعیت تحویل رزرو
    elif query.data.startswith("toggle_delivered_"):
        reservation_id = int(query.data.split("_")[2])
        
        # دریافت رزرو از دیتابیس
        reservation = db_session.query(Reservation).filter_by(id=reservation_id).first()
        
        if reservation:
            # تغییر وضعیت تحویل
            reservation.is_delivered = not reservation.is_delivered
            
            # اگر تحویل شده، زمان تحویل را ثبت می‌کنیم
            if reservation.is_delivered:
                reservation.delivery_time = datetime.datetime.now()
            else:
                reservation.delivery_time = None
            
            db_session.commit()
            
            # به‌روزرسانی پیام
            query.answer(f"وضعیت تحویل به {'تحویل شده' if reservation.is_delivered else 'تحویل نشده'} تغییر یافت.")
            
            # بازگشت به صفحه مدیریت همان وعده
            query.data = f"manage_meal_{reservation.day}_{reservation.meal_type}"
            return handle_callback(update, context)
    
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
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # بررسی مرحله مکالمه کاربر
    user_state = context.user_data.get('state')
    
    # پردازش ویرایش منوی غذا
    if user_state == EDIT_MENU_FOOD and 'edit_day' in context.user_data and 'edit_meal' in context.user_data:
        day = context.user_data['edit_day']
        meal = context.user_data['edit_meal']
        new_food = message_text
        
        # به‌روزرسانی منو در دیتابیس
        menu_item = db_session.query(Menu).filter_by(day=day).first()
        if menu_item:
            # به‌روزرسانی داده‌های JSON
            menu_data_copy = menu_item.meal_data.copy()
            menu_data_copy[meal] = new_food
            menu_item.meal_data = menu_data_copy
            db_session.commit()
            
            # به‌روزرسانی کش منو
            menu_data[day][meal] = new_food
            
            # ارسال پیام تأیید
            update.message.reply_text(
                f"\U00002705 منوی {persian_meals[meal]} روز {persian_days[day]} به «{new_food}» تغییر یافت.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت به مدیریت منو", callback_data="admin_menu")]
                ])
            )
        else:
            update.message.reply_text(
                "\U0001F6AB خطا در به‌روزرسانی منو. لطفاً دوباره تلاش کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
                ])
            )
        
        # پاک کردن وضعیت مکالمه
        context.user_data.pop('state', None)
        context.user_data.pop('edit_day', None)
        context.user_data.pop('edit_meal', None)
        return
        
    # پردازش توضیحات نسخه پشتیبان
    elif user_state == DATABASE_BACKUP_DESC:
        description = message_text
        
        # ایجاد نسخه پشتیبان
        update.message.reply_text("\U0001F4BE در حال تهیه نسخه پشتیبان، لطفاً کمی صبر کنید...")
        create_database_backup(description, user_id, context)
        
        # پاک کردن وضعیت مکالمه
        context.user_data.pop('state', None)
        return
    
    # مدیر می‌تواند با وارد کردن کد تغذیه رزروها را بررسی کند
    if is_owner(user_id):
        code = message_text
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
                    keyboard = []
                    for day, day_reservations in reservations_by_day.items():
                        persian_day = persian_days.get(day, day)
                        message += f"<b>\U0001F4C6 روز {persian_day}:</b>\n"
                        
                        for reservation in day_reservations:
                            persian_meal = persian_meals.get(reservation.meal_type, reservation.meal_type)
                            status = "\U00002705" if reservation.is_delivered else "\U0001F551"
                            message += f"  {status} {persian_meal}: {reservation.food}\n"
                            
                            # اضافه کردن دکمه تغییر وضعیت تحویل
                            if not reservation.is_delivered:
                                keyboard.append([
                                    InlineKeyboardButton(
                                        f"تأیید تحویل {persian_day} - {persian_meal}",
                                        callback_data=f"toggle_delivered_{reservation.id}"
                                    )
                                ])
                        
                        message += "\n"
                    
                    # ارسال پیام با دکمه‌های ناوبری
                    keyboard.append([InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)
                    return
                else:
                    update.message.reply_text(
                        f"\U0001F6AB رزروی برای کد تغذیه {code} یافت نشد.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
                        ])
                    )
                    return
            else:
                update.message.reply_text(
                    f"\U0001F6AB دانشجویی با کد تغذیه {code} یافت نشد.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
                    ])
                )
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

async def main() -> None:
    """شروع ربات."""
    # دریافت توکن ربات از متغیرهای محیطی
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("توکن ربات تلگرام مشخص نشده است. لطفاً متغیر محیطی TELEGRAM_TOKEN را تنظیم کنید.")
        return
    
    # نمایش وضعیت اتصال ربات
    logger.info(f"در حال شروع ربات با توکن: {token[:5]}...{token[-5:]}")
    
    # ایجاد درخواست‌کننده با تنظیمات مناسب
    application = Application.builder().token(token).build()
    
    # اضافه کردن مدیریت‌کننده مکالمه برای ثبت نام و عملیات مدیریتی
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("register", register_command),
        ],
        states={
            FEEDING_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_feeding_code)],
            EDIT_MENU_FOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)],
            DATABASE_BACKUP_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    
    # اضافه کردن مدیریت‌کننده‌ها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("reservations", reservations_command))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # شروع ربات
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # اجرای ربات تا زمان خاتمه
    await application.updater.stop()
    await application.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("ربات با دستور کاربر متوقف شد.")
    except Exception as e:
        logger.error(f"خطا در اجرای ربات: {e}")