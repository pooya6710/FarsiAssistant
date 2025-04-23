from sqlalchemy import Column, Integer, String, ForeignKey, create_engine, JSON, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import os
import json

Base = declarative_base()

# کلاس دانشجو برای نگهداری اطلاعات دانشجویان
class Student(Base):
    __tablename__ = 'students'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False)  # شناسه کاربری تلگرام
    feeding_code = Column(String, unique=True, nullable=False)  # کد تغذیه
    phone = Column(String, nullable=True)  # شماره تلفن برای اطلاع‌رسانی‌ها (اختیاری)
    registration_date = Column(DateTime, default=datetime.now)  # تاریخ ثبت‌نام
    
    # ارتباط یک به چند با رزروها
    reservations = relationship("Reservation", back_populates="student", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Student(user_id={self.user_id}, feeding_code={self.feeding_code})>"

# کلاس رزرو برای نگهداری اطلاعات رزروهای غذا
class Reservation(Base):
    __tablename__ = 'reservations'
    
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)  # کلید خارجی به جدول دانشجویان
    day = Column(String, nullable=False)  # روز هفته (شنبه، یکشنبه، ...)
    meal_type = Column(String, nullable=False)  # نوع وعده غذایی (صبحانه، ناهار، شام)
    food = Column(String, nullable=False)  # نام غذا
    is_delivered = Column(Boolean, default=False)  # وضعیت تحویل غذا
    delivery_time = Column(DateTime, nullable=True)  # زمان تحویل غذا
    reservation_time = Column(DateTime, default=datetime.now)  # زمان ثبت رزرو
    
    # ارتباط با جدول دانشجویان
    student = relationship("Student", back_populates="reservations")
    
    def __repr__(self):
        return f"<Reservation(student_id={self.student_id}, day={self.day}, meal_type={self.meal_type}, food={self.food}, delivered={self.is_delivered})>"

# کلاس منو برای نگهداری منوی غذای هفتگی
class Menu(Base):
    __tablename__ = 'menu'
    
    id = Column(Integer, primary_key=True)
    day = Column(String, nullable=False)  # روز هفته
    meal_data = Column(JSON, nullable=False)  # اطلاعات وعده‌های غذایی در قالب JSON
    
    def __repr__(self):
        return f"<Menu(day={self.day}, meal_data={self.meal_data})>"

# کلاس جدید برای بک‌آپ‌های دیتابیس
class DatabaseBackup(Base):
    __tablename__ = 'backups'
    
    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)  # نام فایل بک‌آپ
    created_at = Column(DateTime, default=datetime.now)  # زمان ایجاد بک‌آپ
    description = Column(Text, nullable=True)  # توضیحات (اختیاری)
    size = Column(Integer, nullable=True)  # سایز فایل بک‌آپ (بایت)
    
    def __repr__(self):
        return f"<DatabaseBackup(filename={self.filename}, created_at={self.created_at})>"

# تابع برای ایجاد اتصال به دیتابیس و جداول
def init_db():
    database_url = os.environ.get('DATABASE_URL')
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # مهاجرت و به‌روزرسانی ساختار دیتابیس
    migrate_database_schema(session, engine)
    
    return session

# تابع برای بارگذاری منوی پیش‌فرض به دیتابیس
def load_default_menu(session):
    # بررسی اینکه آیا منو قبلاً بارگذاری شده است
    menu_count = session.query(Menu).count()
    if menu_count > 0:
        return
    
    # منوی پیش‌فرض
    default_menu = {
        "saturday": {"breakfast": "تخم مرغ", "lunch": "چلوکباب", "dinner": "سوپ"},
        "sunday": {"breakfast": "پنیر و گردو", "lunch": "خورشت قورمه سبزی", "dinner": "ماکارونی"},
        "monday": {"breakfast": "املت", "lunch": "چلو مرغ", "dinner": "کتلت"},
        "tuesday": {"breakfast": "عدسی", "lunch": "خورشت قیمه", "dinner": "کوکو سبزی"},
        "wednesday": {"breakfast": "کره و مربا", "lunch": "آبگوشت", "dinner": "پیتزا"},
        "thursday": {"breakfast": "نان و پنیر", "lunch": "چلو ماهی", "dinner": "سوپ"},
        "friday": {"breakfast": "حلوا ارده", "lunch": "خورشت فسنجان", "dinner": "ساندویچ"}
    }
    
    # افزودن منوی پیش‌فرض به دیتابیس
    for day, meals in default_menu.items():
        menu_item = Menu(day=day, meal_data=meals)
        session.add(menu_item)
    
    session.commit()

# تابع برای ایجاد یا به‌روزرسانی ساختار دیتابیس
def migrate_database_schema(session, engine):
    import sqlalchemy as sa
    from sqlalchemy import inspect
    
    # بررسی ستون‌های موجود در جدول رزروها
    inspector = inspect(engine)
    reservation_columns = [column['name'] for column in inspector.get_columns('reservations')]
    student_columns = [column['name'] for column in inspector.get_columns('students')]
    
    # اضافه کردن ستون‌های مورد نیاز به جدول رزروها
    with engine.connect() as connection:
        if 'is_delivered' not in reservation_columns:
            connection.execute(sa.text("ALTER TABLE reservations ADD COLUMN is_delivered BOOLEAN DEFAULT FALSE"))
        
        if 'delivery_time' not in reservation_columns:
            connection.execute(sa.text("ALTER TABLE reservations ADD COLUMN delivery_time TIMESTAMP"))
        
        if 'reservation_time' not in reservation_columns:
            connection.execute(sa.text("ALTER TABLE reservations ADD COLUMN reservation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
        
        # اضافه کردن ستون‌های مورد نیاز به جدول دانشجویان
        if 'phone' not in student_columns:
            connection.execute(sa.text("ALTER TABLE students ADD COLUMN phone VARCHAR"))
        
        if 'registration_date' not in student_columns:
            connection.execute(sa.text("ALTER TABLE students ADD COLUMN registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
        
        # ایجاد جدول بک‌آپ اگر وجود نداشته باشد
        connection.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS backups (
                id SERIAL PRIMARY KEY,
                filename VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT,
                size INTEGER
            )
        """))
        
        connection.commit()

# تابع برای انتقال داده‌های از فایل JSON به دیتابیس
def migrate_from_json_to_db(json_file, session):
    try:
        with open(json_file, 'r', encoding='utf-8') as file:
            reservations_data = json.load(file)
            
            # نگاشت روزهای فارسی به انگلیسی
            persian_to_english_days = {
                "شنبه": "saturday",
                "یکشنبه": "sunday",
                "دوشنبه": "monday",
                "سه‌شنبه": "tuesday",
                "چهارشنبه": "wednesday",
                "پنج‌شنبه": "thursday",
                "جمعه": "friday"
            }
            
            # نگاشت وعده‌های فارسی به انگلیسی
            persian_to_english_meals = {
                "صبحانه": "breakfast",
                "ناهار": "lunch",
                "شام": "dinner"
            }
            
            # وارد کردن داده‌های رزرو به دیتابیس
            for feeding_code, days in reservations_data.items():
                # بررسی و ایجاد دانشجو
                student = session.query(Student).filter_by(feeding_code=feeding_code).first()
                if not student:
                    student = Student(user_id="unknown", feeding_code=feeding_code)
                    session.add(student)
                    session.flush()  # برای گرفتن شناسه ایجاد شده
                
                # وارد کردن رزروها
                for day_persian, meals in days.items():
                    day_english = persian_to_english_days.get(day_persian, day_persian)
                    
                    for meal_persian, food in meals.items():
                        meal_english = persian_to_english_meals.get(meal_persian, meal_persian)
                        
                        reservation = Reservation(
                            student_id=student.id,
                            day=day_english,
                            meal_type=meal_english,
                            food=food
                        )
                        session.add(reservation)
            
            session.commit()
            return True
    except (FileNotFoundError, json.JSONDecodeError):
        return False