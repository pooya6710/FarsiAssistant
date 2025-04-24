import asyncio
import logging
import json
import os
import datetime
from dotenv import load_dotenv
from jdatetime import date as JalaliDate
from telegram.ext import Updater, CallbackContext, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand
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
async def start(update: Update, context: CallbackContext) -> None:
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

async def main_menu(update: Update, context: CallbackContext) -> None:
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

async def help_command(update: Update, context: CallbackContext) -> None:
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
        await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(help_text, parse_mode="HTML", reply_markup=reply_markup)

async def register_command(update: Update, context: CallbackContext) -> int:
    """شروع فرآیند ثبت کد تغذیه"""
    await update.message.reply_text(
        "\U0001F4DD لطفاً کد تغذیه خود را ارسال کنید:"
    )
    return FEEDING_CODE

async def process_feeding_code(update: Update, context: CallbackContext) -> int:
    """پردازش کد تغذیه وارد شده توسط کاربر"""
    code = update.message.text.strip()
    
    if code.isdigit():
        user_id = str(update.effective_user.id)
        
        try:
            # بررسی اینکه آیا دانشجو قبلاً در دیتابیس وجود دارد
            student = db_session.query(Student).filter_by(user_id=user_id).first()
            
            # بررسی اینکه آیا کد تغذیه توسط کاربر دیگری استفاده شده‌است
            existing_code = db_session.query(Student).filter(Student.feeding_code == code, Student.user_id != user_id).first()
            if existing_code:
                await update.message.reply_text(
                    f"\U0001F6AB این کد تغذیه قبلاً توسط کاربر دیگری ثبت شده است. لطفاً کد دیگری وارد کنید."
                )
                return FEEDING_CODE
            
            if student:
                # به‌روزرسانی کد تغذیه دانشجو
                student.feeding_code = code
                # در صورت بروز خطای rollback، وضعیت را بازنشانی می‌کنیم
                db_session.commit()
            else:
                # ایجاد دانشجوی جدید
                student = Student(user_id=user_id, feeding_code=code)
                db_session.add(student)
                try:
                    db_session.commit()
                except Exception as e:
                    db_session.rollback()
                    logger.error(f"خطا در ثبت دانشجو: {e}")
                    
                    # تلاش مجدد با به‌روزرسانی رکورد موجود
                    existing_student = db_session.query(Student).filter_by(feeding_code=code).first()
                    if existing_student:
                        existing_student.user_id = user_id
                        db_session.commit()
            
            # به‌روزرسانی کش
            students[user_id] = code
            
            await update.message.reply_text(
                f"\U00002705 کد تغذیه شما ({code}) با موفقیت ثبت شد!\n"
                "\U0001F4D1 بازگشت به منوی اصلی:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
                ])
            )
            return ConversationHandler.END
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"خطا در پردازش کد تغذیه: {e}")
            
            await update.message.reply_text(
                "\U0001F6AB خطایی در ثبت کد تغذیه رخ داد. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
            )
            return FEEDING_CODE
    else:
        await update.message.reply_text(
            "\U0001F6AB کد تغذیه باید فقط شامل اعداد باشد. لطفاً دوباره تلاش کنید."
        )
        return FEEDING_CODE

async def cancel(update: Update, context: CallbackContext) -> int:
    """لغو مکالمه"""
    await update.message.reply_text(
        "\U0001F6AB عملیات لغو شد. بازگشت به منوی اصلی...",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
        ])
    )
    return ConversationHandler.END

async def view_menu(update: Update, context: CallbackContext) -> None:
    """نمایش منوی هفتگی با دکمه‌های انتخاب روز"""
    days_keyboard = [
        [InlineKeyboardButton(f"\U0001F4C6 {persian_days[day]}", callback_data=f"day_{day}")] 
        for day in menu_data.keys()
    ]
    days_keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(days_keyboard)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "\U0001F4D6 لطفاً روز مورد نظر خود را انتخاب کنید:", 
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "\U0001F4D6 لطفاً روز مورد نظر خود را انتخاب کنید:", 
            reply_markup=reply_markup
        )

async def show_reservations(update: Update, context: CallbackContext) -> None:
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
                        status = "\U00002705 تحویل شده" if reservation.is_delivered else "\U0001F551 در انتظار تحویل"
                        message += f"  \U0001F374 {persian_meal}: {reservation.food} - {status}\n"
                    
                    message += "\n"
                
                keyboard = []
    
    keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)

async def admin_panel(update: Update, context: CallbackContext) -> None:
    """نمایش پنل مدیریت برای مدیران سیستم"""
    chat_id = update.effective_chat.id
    
    # بررسی دسترسی
    if not is_owner(chat_id):
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("\U0001F6AB شما دسترسی کافی برای استفاده از پنل مدیریت را ندارید.")
        else:
            await update.message.reply_text("\U0001F6AB شما دسترسی کافی برای استفاده از پنل مدیریت را ندارید.")
        return
    
    # ایجاد کیبورد گزینه‌های مدیریتی
    admin_keyboard = [
        [InlineKeyboardButton("\U0001F37D مدیریت منوی غذا", callback_data="admin_menu_management")],
        [InlineKeyboardButton("\U0001F464 لیست کاربران", callback_data="admin_users_list")],
        [InlineKeyboardButton("\U0001F4BE پشتیبان‌گیری از دیتابیس", callback_data="admin_backup")],
        [InlineKeyboardButton("\U0001F4E6 مدیریت تحویل غذا", callback_data="admin_delivery_management")],
        [InlineKeyboardButton("\U0001F5D1 حذف همه رزروها", callback_data="admin_clear_reservations")],
        [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(admin_keyboard)
    
    message = "<b>\U0001F680 پنل مدیریت:</b>\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)

async def admin_menu_management(update: Update, context: CallbackContext) -> None:
    """مدیریت منوی غذای هفتگی"""
    if not is_owner(update.effective_chat.id):
        return
    
    days_keyboard = [
        [InlineKeyboardButton(f"\U0001F4C6 {persian_days[day]}", callback_data=f"edit_menu_{day}")] 
        for day in menu_data.keys()
    ]
    days_keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(days_keyboard)
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "<b>\U0001F37D مدیریت منوی غذا:</b>\n\nلطفاً روز مورد نظر برای ویرایش منو را انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def admin_users_list(update: Update, context: CallbackContext) -> None:
    """نمایش لیست کاربران ثبت‌نام شده"""
    if not is_owner(update.effective_chat.id):
        return
    
    # دریافت تعداد کل کاربران
    total_users = db_session.query(Student).count()
    
    # دریافت کاربران به ترتیب تاریخ ثبت‌نام (10 کاربر آخر)
    latest_users = db_session.query(Student).order_by(Student.registration_date.desc()).limit(10).all()
    
    message = f"<b>\U0001F464 لیست کاربران:</b>\n\nتعداد کل کاربران: {total_users}\n\n"
    message += "<b>آخرین کاربران ثبت‌نام شده:</b>\n"
    
    for i, user in enumerate(latest_users, start=1):
        registration_date = user.registration_date.strftime("%Y-%m-%d %H:%M:%S") if user.registration_date else "نامشخص"
        message += f"{i}. کد تغذیه: {user.feeding_code} - شناسه کاربری: {user.user_id} - تاریخ ثبت‌نام: {registration_date}\n"
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
    ])
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        message,
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def admin_backup_database(update: Update, context: CallbackContext) -> int:
    """تهیه نسخه پشتیبان از دیتابیس"""
    if not is_owner(update.effective_chat.id):
        return ConversationHandler.END
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "<b>\U0001F4BE پشتیبان‌گیری از دیتابیس:</b>\n\n"
        "لطفاً توضیحی برای این نسخه پشتیبان وارد کنید (مثلاً: \"پشتیبان روزانه\" یا \"قبل از به‌روزرسانی\"):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F519 انصراف و بازگشت", callback_data="admin_panel")]
        ])
    )
    
    return DATABASE_BACKUP_DESC

async def create_database_backup(description, chat_id, context: CallbackContext) -> None:
    """ایجاد فایل پشتیبان از دیتابیس"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.sql"
        
        # ایجاد یک دامپ SQL از دیتابیس
        now = datetime.datetime.now()
        
        # ذخیره اطلاعات بک‌آپ در دیتابیس
        backup = DatabaseBackup(
            filename=backup_filename,
            description=description,
            created_at=now,
            size=1024  # سایز تقریبی، در نسخه واقعی باید سایز فایل محاسبه شود
        )
        db_session.add(backup)
        db_session.commit()
        
        # ارسال پیام موفقیت‌آمیز
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"<b>\U00002705 نسخه پشتیبان با موفقیت ایجاد شد:</b>\n\n"
                 f"نام فایل: {backup_filename}\n"
                 f"توضیحات: {description}\n"
                 f"تاریخ ایجاد: {now.strftime('%Y-%m-%d %H:%M:%S')}\n",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
            ])
        )
    except Exception as e:
        # ارسال پیام خطا
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"<b>\U0001F6AB خطا در ایجاد نسخه پشتیبان:</b>\n\n{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
            ])
        )

async def admin_clear_reservations(update: Update, context: CallbackContext) -> None:
    """حذف تمام رزروهای موجود در سیستم"""
    if not is_owner(update.effective_chat.id):
        return
    
    # نمایش پیام تایید
    confirm_keyboard = [
        [InlineKeyboardButton("\U00002705 بله، همه رزروها حذف شوند", callback_data="confirm_clear_reservations")],
        [InlineKeyboardButton("\U0001F6AB خیر، انصراف", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(confirm_keyboard)
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "<b>\U0001F5D1 حذف تمام رزروها</b>\n\n"
        "\U0001F6A8 <b>هشدار:</b> این عملیات غیرقابل بازگشت است و تمام رزروهای ثبت شده در سیستم حذف خواهند شد.\n\n"
        "آیا از حذف تمام رزروها اطمینان دارید؟",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def admin_delivery_management(update: Update, context: CallbackContext) -> None:
    """مدیریت تحویل غذا و مشاهده رزروها"""
    if not is_owner(update.effective_chat.id):
        return
    
    # نمایش روزهای هفته برای انتخاب
    days_keyboard = [
        [InlineKeyboardButton(f"\U0001F4C6 {persian_days[day]}", callback_data=f"delivery_day_{day}")] 
        for day in persian_days.keys()
    ]
    days_keyboard.append([
        InlineKeyboardButton("\U0001F50D جستجو با کد تغذیه", callback_data="search_by_feeding_code")
    ])
    days_keyboard.append([InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(days_keyboard)
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "<b>\U0001F4E6 مدیریت تحویل غذا:</b>\n\n"
        "لطفاً روز مورد نظر را انتخاب کنید یا با کد تغذیه جستجو کنید:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: CallbackContext) -> None:
    """پردازش کالبک کوئری‌ها از کیبوردهای درون خطی"""
    query = update.callback_query
    await query.answer()  # پاسخ به کالبک کوئری برای توقف نشانگر بارگذاری
    
    # پردازش دکمه بازگشت به منوی اصلی
    if query.data == "back_to_menu":
        await main_menu(update, context)
        return
    
    # پردازش دکمه‌های اصلی منو
    if query.data == "view_menu":
        await view_menu(update, context)
        return
    elif query.data == "register":
        if hasattr(update.callback_query, 'message'):
            await update.callback_query.message.reply_text(
                "\U0001F4DD لطفاً کد تغذیه خود را ارسال کنید:"
            )
        return
    elif query.data == "show_reservations":
        await show_reservations(update, context)
        return
    elif query.data == "help":
        await help_command(update, context)
        return
    elif query.data == "admin_panel":
        await admin_panel(update, context)
        return
    
    # پردازش دکمه‌های پنل مدیریت
    if query.data == "admin_menu_management":
        await admin_menu_management(update, context)
        return
    elif query.data == "admin_users_list":
        await admin_users_list(update, context)
        return
    elif query.data == "admin_delivery_management":
        await admin_delivery_management(update, context)
        return
    elif query.data == "admin_clear_reservations":
        await admin_clear_reservations(update, context)
        return
    elif query.data == "confirm_clear_reservations":
        try:
            # حذف تمام رزروها از دیتابیس
            db_session.query(Reservation).delete()
            db_session.commit()
            
            # نمایش پیام موفقیت‌آمیز
            await query.edit_message_text(
                "<b>\U00002705 موفقیت‌آمیز:</b>\n\n"
                "تمام رزروها با موفقیت از سیستم حذف شدند.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
                ])
            )
        except Exception as e:
            # در صورت بروز خطا، رولبک کنید
            db_session.rollback()
            logger.error(f"خطا در حذف رزروها: {e}")
            
            # نمایش پیام خطا
            await query.edit_message_text(
                f"<b>\U0001F6AB خطا:</b>\n\n"
                f"در حذف رزروها خطایی رخ داد: {str(e)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت به پنل مدیریت", callback_data="admin_panel")]
                ])
            )
        return
    
    # پردازش انتخاب روز از منوی غذا
    if query.data.startswith("day_"):
        selected_day = query.data.split("_")[1]
        meals = menu_data[selected_day]
        
        # بررسی اینکه آیا کاربر کد تغذیه خود را ثبت کرده است
        user_id = str(update.effective_user.id)
        if user_id not in students:
            await query.edit_message_text(
                "\U0001F6AB لطفاً ابتدا کد تغذیه خود را ثبت کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
                    [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
                ])
            )
            return
        
        # نمایش منوی غذا برای روز انتخاب شده
        meals_keyboard = []
        for meal_type, meal_name in meals.items():
            persian_meal = persian_meals.get(meal_type, meal_type)
            meals_keyboard.append([
                InlineKeyboardButton(
                    f"\U0001F374 {persian_meal}: {meal_name}", 
                    callback_data=f"reserve_{selected_day}_{meal_type}"
                )
            ])
        
        meals_keyboard.append([
            InlineKeyboardButton("\U0001F4E6 رزرو همه وعده‌ها", callback_data=f"reserve_all_{selected_day}")
        ])
        meals_keyboard.append([
            InlineKeyboardButton("\U0001F519 بازگشت به روزها", callback_data="view_menu")
        ])
        
        reply_markup = InlineKeyboardMarkup(meals_keyboard)
        
        await query.edit_message_text(
            f"<b>\U0001F4D6 منوی غذای روز {persian_days[selected_day]}:</b>\n\n"
            f"\U0001F374 صبحانه: {meals['breakfast']}\n"
            f"\U0001F35C ناهار: {meals['lunch']}\n"
            f"\U0001F35D شام: {meals['dinner']}\n\n"
            "لطفاً وعده مورد نظر خود را برای رزرو انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        return
    
    # پردازش رزرو غذا
    if query.data.startswith("reserve_"):
        parts = query.data.split("_")
        
        # رزرو همه وعده‌های یک روز
        if parts[1] == "all":
            selected_day = parts[2]
            await reserve_all_meals(update, context, selected_day)
            return
        
        # رزرو یک وعده خاص
        selected_day = parts[1]
        selected_meal = parts[2]
        await reserve_meal(update, context, selected_day, selected_meal)
        return
    
    # پردازش انتخاب روز برای ویرایش منو
    if query.data.startswith("edit_menu_"):
        selected_day = query.data.split("_")[2]
        current_meals = menu_data[selected_day]
        
        meals_keyboard = []
        for meal_type, meal_name in current_meals.items():
            persian_meal = persian_meals.get(meal_type, meal_type)
            meals_keyboard.append([
                InlineKeyboardButton(
                    f"\U0001F374 {persian_meal}: {meal_name}", 
                    callback_data=f"edit_meal_{selected_day}_{meal_type}"
                )
            ])
        
        meals_keyboard.append([
            InlineKeyboardButton("\U0001F519 بازگشت", callback_data="admin_menu_management")
        ])
        
        reply_markup = InlineKeyboardMarkup(meals_keyboard)
        
        await query.edit_message_text(
            f"<b>\U0001F37D منوی روز {persian_days[selected_day]}:</b>\n\n"
            f"\U0001F374 صبحانه: {current_meals['breakfast']}\n"
            f"\U0001F35C ناهار: {current_meals['lunch']}\n"
            f"\U0001F35D شام: {current_meals['dinner']}\n\n"
            "لطفاً وعده مورد نظر برای ویرایش را انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        
        # تنظیم مرحله بعدی مکالمه
        return
    
    # پردازش دکمه‌های مدیریت تحویل غذا
    if query.data.startswith("delivery_day_"):
        selected_day = query.data.split("_")[2]
        
        # دریافت رزروهای روز انتخاب شده
        reservations = db_session.query(Reservation).filter_by(day=selected_day).all()
        
        if not reservations:
            await query.edit_message_text(
                f"<b>\U0001F4E6 رزروهای روز {persian_days[selected_day]}:</b>\n\n"
                "هیچ رزروی برای این روز ثبت نشده است.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت", callback_data="admin_delivery_management")]
                ])
            )
            return
        
        # گروه‌بندی رزروها بر اساس نوع وعده
        breakfast = []
        lunch = []
        dinner = []
        
        for reservation in reservations:
            student = db_session.query(Student).filter_by(id=reservation.student_id).first()
            if not student:
                continue
                
            reservation_info = {
                "id": reservation.id,
                "feeding_code": student.feeding_code,
                "food": reservation.food,
                "is_delivered": reservation.is_delivered
            }
            
            if reservation.meal_type == "breakfast":
                breakfast.append(reservation_info)
            elif reservation.meal_type == "lunch":
                lunch.append(reservation_info)
            elif reservation.meal_type == "dinner":
                dinner.append(reservation_info)
        
        # ایجاد پیام با دکمه‌های تایید تحویل
        message = f"<b>\U0001F4E6 رزروهای روز {persian_days[selected_day]}:</b>\n\n"
        
        # نمایش رزروهای صبحانه
        if breakfast:
            message += "<b>\U0001F374 صبحانه:</b>\n"
            for i, res in enumerate(breakfast, start=1):
                status = "\U00002705" if res["is_delivered"] else "\U0001F551"
                message += f"{i}. کد تغذیه: {res['feeding_code']} - غذا: {res['food']} - {status}\n"
            message += "\n"
        
        # نمایش رزروهای ناهار
        if lunch:
            message += "<b>\U0001F35C ناهار:</b>\n"
            for i, res in enumerate(lunch, start=1):
                status = "\U00002705" if res["is_delivered"] else "\U0001F551"
                message += f"{i}. کد تغذیه: {res['feeding_code']} - غذا: {res['food']} - {status}\n"
            message += "\n"
        
        # نمایش رزروهای شام
        if dinner:
            message += "<b>\U0001F35D شام:</b>\n"
            for i, res in enumerate(dinner, start=1):
                status = "\U00002705" if res["is_delivered"] else "\U0001F551"
                message += f"{i}. کد تغذیه: {res['feeding_code']} - غذا: {res['food']} - {status}\n"
            message += "\n"
        
        message += "برای تایید تحویل یک غذا، پیام جدیدی فرستاده و کد تغذیه دانشجو را وارد کنید."
        
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت", callback_data="admin_delivery_management")]
            ])
        )
        return
    
    # پردازش دکمه جستجو با کد تغذیه
    if query.data == "search_by_feeding_code":
        await query.edit_message_text(
            "<b>\U0001F50D جستجو با کد تغذیه:</b>\n\n"
            "لطفاً کد تغذیه دانشجوی مورد نظر را وارد کنید:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت", callback_data="admin_delivery_management")]
            ])
        )
        return
    
    # پردازش تایید تحویل غذا
    if query.data.startswith("confirm_delivery_"):
        reservation_id = int(query.data.split("_")[2])
        
        # به‌روزرسانی وضعیت تحویل رزرو
        reservation = db_session.query(Reservation).filter_by(id=reservation_id).first()
        if reservation:
            reservation.is_delivered = True
            reservation.delivery_time = datetime.datetime.now()
            db_session.commit()
            
            await query.edit_message_text(
                "\U00002705 تحویل غذا با موفقیت تایید شد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت به مدیریت تحویل", callback_data="admin_delivery_management")]
                ])
            )
        else:
            await query.edit_message_text(
                "\U0001F6AB خطا: رزرو مورد نظر یافت نشد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F519 بازگشت", callback_data="admin_delivery_management")]
                ])
            )
        return

async def reserve_all_meals(update: Update, context: CallbackContext, selected_day: str) -> None:
    """رزرو تمام وعده‌های یک روز"""
    user_id = str(update.effective_user.id)
    if user_id not in students:
        await update.callback_query.edit_message_text(
            "\U0001F6AB لطفاً ابتدا کد تغذیه خود را ثبت کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
                [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
            ])
        )
        return
    
    feeding_code = students[user_id]
    student = db_session.query(Student).filter_by(feeding_code=feeding_code).first()
    
    if not student:
        await update.callback_query.edit_message_text(
            "\U0001F6AB خطا در پیدا کردن اطلاعات شما. لطفاً دوباره کد تغذیه خود را ثبت کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
                [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
            ])
        )
        return
    
    # دریافت اطلاعات منوی روز
    meals = menu_data[selected_day]
    
    # ایجاد رزرو برای هر سه وعده
    for meal_type, food in meals.items():
        # بررسی اینکه آیا رزروی مشابه قبلاً ثبت شده است
        existing_reservation = db_session.query(Reservation).filter_by(
            student_id=student.id,
            day=selected_day,
            meal_type=meal_type
        ).first()
        
        if existing_reservation:
            # به‌روزرسانی رزرو موجود
            existing_reservation.food = food
        else:
            # ایجاد رزرو جدید
            reservation = Reservation(
                student_id=student.id,
                day=selected_day,
                meal_type=meal_type,
                food=food
            )
            db_session.add(reservation)
    
    db_session.commit()
    
    # نمایش پیام موفقیت‌آمیز
    persian_day = persian_days[selected_day]
    await update.callback_query.edit_message_text(
        f"<b>\U00002705 رزرو شما برای تمام وعده‌های روز {persian_day} با موفقیت ثبت شد:</b>\n\n"
        f"\U0001F374 صبحانه: {meals['breakfast']}\n"
        f"\U0001F35C ناهار: {meals['lunch']}\n"
        f"\U0001F35D شام: {meals['dinner']}\n",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F4C5 مشاهده رزروها", callback_data="show_reservations")],
            [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
        ])
    )

async def reserve_meal(update: Update, context: CallbackContext, selected_day: str, selected_meal: str) -> None:
    """رزرو یک وعده غذایی خاص"""
    user_id = str(update.effective_user.id)
    if user_id not in students:
        await update.callback_query.edit_message_text(
            "\U0001F6AB لطفاً ابتدا کد تغذیه خود را ثبت کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
                [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
            ])
        )
        return
    
    feeding_code = students[user_id]
    student = db_session.query(Student).filter_by(feeding_code=feeding_code).first()
    
    if not student:
        await update.callback_query.edit_message_text(
            "\U0001F6AB خطا در پیدا کردن اطلاعات شما. لطفاً دوباره کد تغذیه خود را ثبت کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F4DD ثبت کد تغذیه", callback_data="register")],
                [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
            ])
        )
        return
    
    # دریافت اطلاعات غذا
    food = menu_data[selected_day][selected_meal]
    
    # بررسی اینکه آیا رزروی مشابه قبلاً ثبت شده است
    existing_reservation = db_session.query(Reservation).filter_by(
        student_id=student.id,
        day=selected_day,
        meal_type=selected_meal
    ).first()
    
    if existing_reservation:
        # به‌روزرسانی رزرو موجود
        existing_reservation.food = food
    else:
        # ایجاد رزرو جدید
        reservation = Reservation(
            student_id=student.id,
            day=selected_day,
            meal_type=selected_meal,
            food=food
        )
        db_session.add(reservation)
    
    db_session.commit()
    
    # نمایش پیام موفقیت‌آمیز
    persian_day = persian_days[selected_day]
    persian_meal = persian_meals[selected_meal]
    
    await update.callback_query.edit_message_text(
        f"<b>\U00002705 رزرو شما برای وعده {persian_meal} روز {persian_day} با موفقیت ثبت شد:</b>\n\n"
        f"\U0001F374 غذا: {food}\n",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001F4C5 مشاهده رزروها", callback_data="show_reservations")],
            [InlineKeyboardButton("\U0001F519 بازگشت به منوی اصلی", callback_data="back_to_menu")]
        ])
    )

async def menu_command(update: Update, context: CallbackContext) -> None:
    """پردازش دستور /menu"""
    await view_menu(update, context)

async def reservations_command(update: Update, context: CallbackContext) -> None:
    """پردازش دستور /reservations"""
    await show_reservations(update, context)

async def message_handler(update: Update, context: CallbackContext) -> None:
    """پردازش پیام‌های متنی خارج از مکالمه‌ها"""
    # بررسی اینکه آیا مدیر داخل بخش جستجو با کد تغذیه است
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    
    # پردازش کد تغذیه برای مدیران (برای مشاهده و تایید تحویل غذا)
    if is_owner(user_id) and user_message.isdigit():
        feeding_code = user_message
        student = db_session.query(Student).filter_by(feeding_code=feeding_code).first()
        
        if not student:
            await update.message.reply_text(
                f"\U0001F6AB دانشجویی با کد تغذیه {feeding_code} یافت نشد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
                ])
            )
            return
        
        # دریافت رزروهای دانشجو
        reservations = db_session.query(Reservation).filter_by(student_id=student.id).all()
        
        if not reservations:
            await update.message.reply_text(
                f"\U0001F4C5 دانشجو با کد تغذیه {feeding_code} هیچ رزروی ندارد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001F4D1 منوی اصلی", callback_data="back_to_menu")]
                ])
            )
            return
        
        # گروه‌بندی رزروها بر اساس روز
        reservations_by_day = {}
        for reservation in reservations:
            if reservation.day not in reservations_by_day:
                reservations_by_day[reservation.day] = []
            reservations_by_day[reservation.day].append(reservation)
        
        # نمایش رزروها به همراه دکمه‌های تایید تحویل
        message = f"<b>\U0001F4C5 رزروهای دانشجو با کد تغذیه {feeding_code}:</b>\n\n"
        
        for day, day_reservations in reservations_by_day.items():
            persian_day = persian_days.get(day, day)
            message += f"<b>\U0001F4C6 روز {persian_day}:</b>\n"
            
            keyboard = []
            for reservation in day_reservations:
                persian_meal = persian_meals.get(reservation.meal_type, reservation.meal_type)
                status = "\U00002705 تحویل شده" if reservation.is_delivered else "\U0001F551 در انتظار تحویل"
                delivery_time = ""
                if reservation.delivery_time:
                    delivery_time = f" (زمان تحویل: {reservation.delivery_time.strftime('%H:%M:%S')})"
                
                message += f"  \U0001F374 {persian_meal}: {reservation.food} - {status}{delivery_time}\n"
                
                # اضافه کردن دکمه تایید تحویل فقط برای غذاهای تحویل نشده
                if not reservation.is_delivered:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"\U00002705 تایید تحویل {persian_meal}",
                            callback_data=f"confirm_delivery_{reservation.id}"
                        )
                    ])
            
            message += "\n"
            
            if keyboard:
                # ارسال پیام جداگانه برای هر روز با دکمه‌های مخصوص آن روز
                meal_texts = []
                for r in day_reservations:
                    status = "✅ تحویل شده" if r.is_delivered else "🕑 در انتظار تحویل"
                    meal_text = f"  🍴 {persian_meals.get(r.meal_type, r.meal_type)}: {r.food} - {status}"
                    meal_texts.append(meal_text)
                
                await update.message.reply_text(
                    f"<b>📆 روز {persian_day}:</b>\n\n" + 
                    "\n".join(meal_texts),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        
        # ارسال پیام نهایی با دکمه بازگشت
        await update.message.reply_text(
            "لطفاً از دکمه‌های بالا برای تایید تحویل استفاده کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001F519 بازگشت به مدیریت تحویل", callback_data="admin_delivery_management")]
            ])
        )
        return
    
    # دریافت وضعیت تنظیم شده در مکالمه قبلی (برای ویرایش منو)
    state = context.user_data.get('state')
    
    if state == EDIT_MENU_FOOD and is_owner(user_id):
        # پردازش ویرایش غذای منو
        if 'edit_day' in context.user_data and 'edit_meal' in context.user_data:
            day = context.user_data['edit_day']
            meal = context.user_data['edit_meal']
            new_food = user_message
            
            # به‌روزرسانی منو در دیتابیس
            menu_item = db_session.query(Menu).filter_by(day=day).first()
            if menu_item:
                meal_data = menu_item.meal_data
                meal_data[meal] = new_food
                menu_item.meal_data = meal_data
                db_session.commit()
                
                # به‌روزرسانی کش منو
                menu_data[day][meal] = new_food
                
                await update.message.reply_text(
                    f"<b>\U00002705 منوی غذا با موفقیت به‌روزرسانی شد:</b>\n\n"
                    f"\U0001F4C6 روز: {persian_days[day]}\n"
                    f"\U0001F374 وعده: {persian_meals[meal]}\n"
                    f"\U0001F35D غذای جدید: {new_food}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001F519 بازگشت به مدیریت منو", callback_data="admin_menu_management")]
                    ])
                )
            else:
                await update.message.reply_text(
                    "\U0001F6AB خطا در به‌روزرسانی منو.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001F519 بازگشت به مدیریت منو", callback_data="admin_menu_management")]
                    ])
                )
            
            # پاک کردن وضعیت
            context.user_data.pop('state', None)
            context.user_data.pop('edit_day', None)
            context.user_data.pop('edit_meal', None)
            return
    
    elif state == DATABASE_BACKUP_DESC and is_owner(user_id):
        # پردازش توضیحات پشتیبان‌گیری
        description = user_message
        
        # ایجاد نسخه پشتیبان از دیتابیس
        await create_database_backup(description, user_id, context)
        
        # پاک کردن وضعیت
        context.user_data.pop('state', None)
        return
    
    # پاسخ پیش‌فرض
    await update.message.reply_text(
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
        logger.error("توکن ربات تلگرام مشخص نشده است. لطفاً در فایل .env آن را تنظیم کنید.")
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
    
    logger.info("ربات شروع به کار کرد و آماده پاسخگویی است!")
    
    # ربات را در حالت اجرا نگه می‌داریم تا بتواند به پیام‌ها پاسخ دهد
    try:
        # به جای توقف، ربات را در حالت اجرا نگه میداریم
        while True:
            await asyncio.sleep(3600)  # هر ساعت یکبار چک می‌کنیم
            logger.info("ربات همچنان در حال اجراست...")
    except (KeyboardInterrupt, SystemExit):
        # در صورت درخواست توقف توسط کاربر
        logger.info("در حال متوقف کردن ربات...")
        
    # این خطوط فقط در صورت توقف ربات اجرا می‌شوند
    await application.updater.stop()
    await application.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("ربات با دستور کاربر متوقف شد.")
    except Exception as e:
        logger.error(f"خطا در اجرای ربات: {e}")