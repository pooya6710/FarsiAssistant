from sqlalchemy import Column, Integer, String, ForeignKey, create_engine, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import os
import json

Base = declarative_base()

# کلاس دانشجو برای نگهداری اطلاعات دانشجویان
class Student(Base):
    __tablename__ = 'students'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False)  # شناسه کاربری تلگرام
    feeding_code = Column(String, unique=True, nullable=False)  # کد تغذیه
    
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
    
    # ارتباط با جدول دانشجویان
    student = relationship("Student", back_populates="reservations")
    
    def __repr__(self):
        return f"<Reservation(student_id={self.student_id}, day={self.day}, meal_type={self.meal_type}, food={self.food})>"

# کلاس منو برای نگهداری منوی غذای هفتگی
class Menu(Base):
    __tablename__ = 'menu'
    
    id = Column(Integer, primary_key=True)
    day = Column(String, nullable=False)  # روز هفته
    meal_data = Column(JSON, nullable=False)  # اطلاعات وعده‌های غذایی در قالب JSON
    
    def __repr__(self):
        return f"<Menu(day={self.day}, meal_data={self.meal_data})>"

# تابع برای ایجاد اتصال به دیتابیس و جداول
def init_db():
    database_url = os.environ.get('DATABASE_URL')
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

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