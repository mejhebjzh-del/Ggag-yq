import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# 1. إعداد قراءة التوكن
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 2. إعداد السجلات (Logging)
logging.basicConfig(level=logging.INFO)

# 3. تهيئة البوت والموزع
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# 4. أوامر البوت
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(f"أهلاً بك يا {message.from_user.full_name}!\nأنا بوتك الاحترافي الأول.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("الأوامر المتاحة:\n/start - بدء البوت\n/help - المساعدة")

# 5. دالة التشغيل الرئيسية
async def main():
    print("🚀 البوت يعمل الآن...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
