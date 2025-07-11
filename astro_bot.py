import logging
import os
import requests
from aiogram import Bot, Dispatcher, executor, types
from flatlib.chart import Chart
from flatlib.geopos import GeoPos
from flatlib.datetime import Datetime
from flatlib import const
from dotenv import load_dotenv
import openai

from timezonefinder import TimezoneFinder
import pytz
from datetime import datetime

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
openai.api_key = OPENAI_API_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

user_data = {}

# ✅ Добавляем кнопки, которые появятся после ответов
after_natal_keyboard = types.InlineKeyboardMarkup()
after_natal_keyboard.add(
    types.InlineKeyboardButton("🔮 Получить гороскоп на день", callback_data="daily_horoscope")
)

after_horoscope_keyboard = types.InlineKeyboardMarkup()
after_horoscope_keyboard.add(
    types.InlineKeyboardButton("🪐 Рассчитать натальную карту", callback_data="show_natal_chart")
)

def get_coords(city_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city_name, "format": "json", "limit": 1}
    try:
        response = requests.get(url, params=params, headers={"User-Agent": "astro-bot"})
        data = response.json()
        if data:
            lat = float(data[0]['lat'])
            lon = float(data[0]['lon'])
            return lat, lon
    except Exception as e:
        logging.error(f"Ошибка при получении координат: {e}")
    return None, None

def dec_to_dms(deg):
    d = int(deg)
    m_float = abs(deg - d) * 60
    m = int(m_float)
    s = int((m_float - m) * 60)
    return f"{abs(d)}:{m}:{s}"

def get_utc_offset(lat, lon, date_str, time_str):
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    if tz_name is None:
        return "+00:00"
    tz = pytz.timezone(tz_name)
    dt_naive = datetime.strptime(date_str + ' ' + time_str, "%Y/%m/%d %H:%M")
    try:
        dt_aware = tz.localize(dt_naive, is_dst=None)
    except pytz.exceptions.AmbiguousTimeError:
        dt_aware = tz.localize(dt_naive, is_dst=True)

    offset_sec = dt_aware.utcoffset().total_seconds()
    hours = int(offset_sec // 3600)
    minutes = int((abs(offset_sec) % 3600) // 60)
    sign = '+' if hours >= 0 else '-'
    return f"{sign}{abs(hours):02d}:{minutes:02d}"

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    # Сохраняем имя пользователя
    user_data[message.from_user.id] = {
        'first_name': message.from_user.first_name  # Сохраняем имя пользователя
    }
    await message.reply(
        f"👋 Привет, {message.from_user.first_name}! Я Астробот. Давай составим твою натальную карту.\n"
        "Введите свою дату рождения (например: 17.04.1995):"
    )
    
@dp.message_handler(lambda message: message.from_user.id in user_data and 'birth_date' not in user_data[message.from_user.id])
async def get_birth_date(message: types.Message):
    date_text = message.text.strip()
    user_first_name = user_data[message.from_user.id].get('first_name', 'друг')  # Получаем имя пользователя
    
    try:
        datetime.strptime(date_text, "%d.%m.%Y")
    except ValueError:
        await message.reply(f"❌ Неверный формат даты, {user_first_name}. Пожалуйста, введи дату в формате ДД.ММ.ГГГГ (например, 17.04.1995).")
        return

    user_data[message.from_user.id]['birth_date'] = date_text
    await message.reply(f"⏰ Спасибо, {user_first_name}! Теперь укажи время рождения (в 24-часовом формате, например: 13:45):")

@dp.message_handler(lambda message: message.from_user.id in user_data and 'birth_time' not in user_data[message.from_user.id])
async def get_birth_time(message: types.Message):
    time_text = message.text.strip()
    user_first_name = user_data[message.from_user.id].get('first_name', 'друг')  # Получаем имя пользователя
    
    try:
        datetime.strptime(time_text, "%H:%M")
    except ValueError:
        await message.reply(f"❌ Неверный формат времени, {user_first_name}. Пожалуйста, введи время в формате ЧЧ:ММ (например, 13:45).")
        return

    user_data[message.from_user.id]['birth_time'] = time_text
    await message.reply(f"🌍 Отлично, {user_first_name}! Теперь введи город рождения (например: Вена):")

@dp.message_handler(lambda message: message.from_user.id in user_data and 'birth_place' not in user_data[message.from_user.id])
async def get_birth_place(message: types.Message):
    city_name = message.text.strip()
    user_first_name = user_data[message.from_user.id].get('first_name', 'друг')  # Получаем имя пользователя
    
    user_data[message.from_user.id]['birth_place'] = city_name

    lat, lon = get_coords(city_name)
    if lat is not None and lon is not None:
        pos = GeoPos(dec_to_dms(lat), dec_to_dms(lon))
    else:
        await message.reply(f"⚠️ Не удалось определить координаты города {city_name}, {user_first_name}. Использую Москву по умолчанию.")
        lat, lon = 55.7558, 37.6173
        pos = GeoPos("55:45:21", "37:37:03")

    date = user_data[message.from_user.id]['birth_date']
    time = user_data[message.from_user.id]['birth_time']

    try:
        d, m, y = date.split('.')
        date_formatted = f"{y}/{m}/{d}"
    except Exception:
        await message.reply(f"❌ Ошибка в формате даты, {user_first_name}. Пожалуйста, введи дату в формате ДД.ММ.ГГГГ")
        return

    try:
        offset = get_utc_offset(lat, lon, date_formatted, time)
    except Exception as e:
        await message.reply(f"❌ Ошибка при определении часового пояса, {user_first_name}: {e}")
        return

    try:
        dt = Datetime(date_formatted, time, offset)
    except Exception as e:
        await message.reply(f"❌ Ошибка при создании объекта времени, {user_first_name}: {e}")
        return

    try:
        chart = Chart(dt, pos, IDs=[ 
            const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
            const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO,
            const.NORTH_NODE, const.SOUTH_NODE
        ])
    except Exception as e:
        await message.reply(f"❌ Ошибка при создании астрологической карты, {user_first_name}: {e}")
        return

    signs_emoji = {
        'Aries': '♈️ Овен', 'Taurus': '♉️ Телец', 'Gemini': '♊️ Близнецы',
        'Cancer': '♋️ Рак', 'Leo': '♌️ Лев', 'Virgo': '♍️ Дева',
        'Libra': '♎️ Весы', 'Scorpio': '♏️ Скорпион', 'Sagittarius': '♐️ Стрелец',
        'Capricorn': '♑️ Козерог', 'Aquarius': '♒️ Водолей', 'Pisces': '♓️ Рыбы',
    }

    names = {
        const.SUN: 'Солнце', const.MOON: 'Луна', const.MERCURY: 'Меркурий',
        const.VENUS: 'Венера', const.MARS: 'Марс', const.JUPITER: 'Юпитер',
        const.SATURN: 'Сатурн', const.URANUS: 'Уран', const.NEPTUNE: 'Нептун',
        const.PLUTO: 'Плутон', const.NORTH_NODE: 'Восходящий узел', const.SOUTH_NODE: 'Нисходящий узел'
    }

    info_lines = []
    for planet in names:
        obj = chart.get(planet)
        if obj:
            emoji = signs_emoji.get(obj.sign, obj.sign)
            info_lines.append(f"• {names[planet]}: {emoji}")

    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("Рассчитать натальную карту", callback_data="show_natal_chart"),
        types.InlineKeyboardButton("Получить гороскоп на день", callback_data="daily_horoscope")
    )

    await message.reply(
        f"🪐 Вот твоя карта, {user_first_name}:\n" +
        "\n".join(info_lines) +
        "\n\nХочешь подробную интерпретацию или гороскоп на сегодня? Просто нажми одну из кнопок 👇",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data == 'show_natal_chart')
async def show_natal_chart_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user = user_data.get(user_id)

    try:
        await callback_query.answer("✨ Считаем твою натальную карту...")
    except Exception as e:
        logging.warning(f"Не удалось ответить на callback_query: {e}")

    if not user:
        await bot.send_message(user_id, "Сначала отправь /start и введи свои данные ✨")
        return

    user_first_name = user.get('first_name', 'друг')  # Получаем имя пользователя

    prompt = (
        f"Ты профессиональный астролог.\n"
        f"У пользователя дата рождения: {user['birth_date']}, "
        f"время: {user['birth_time']}, "
        f"место: {user['birth_place']}.\n"
        f"Составь подробную интерпретацию натальной карты на основе этих данных.\n"
        f"Используй реальные астрологические факты.\n"
        f"Выделяй названия планет и знаков Зодиака **жирным шрифтом**, "
        f"рядом с ними добавляй соответствующие эмоджи (например, ☀️ для **Солнце**, ♈️ для **Овен**).\n"
        f"Пиши красиво, вдохновляюще, но содержательно.\n\n"
        f"❗ Вместо заголовков `#`, используй просто **жирный текст** и эмоджи:\n"
        f"Например:\n"
        f"**🪐 Планеты**\n"
        f"**🏠 Дома**\n"
        f"**🔗 Аспекты**\n"
        f"**🔮 Общая картина**\n"
    )

    try:
        typing_msg = await bot.send_message(user_id, "✍️ Бот печатает натальную карту...")
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
        )
        answer = response.choices[0].message.content
        await bot.delete_message(chat_id=user_id, message_id=typing_msg.message_id)        
    except Exception as e:
        logging.error(f"Ошибка при запросе к OpenAI: {e}")
        await bot.send_message(user_id, f"❌ Произошла ошибка при получении натальной карты, {user_first_name}.")
        return

    await bot.send_message(user_id, f"🌟 Вот твоя натальная карта, {user_first_name}:\n{answer}", parse_mode="Markdown", reply_markup=after_natal_keyboard)

@dp.message_handler()
async def chat_with_gpt(message: types.Message):
    user_id = message.from_user.id          # ← добавили
    user = user_data.get(message.from_user.id)
    if not user:
        await message.reply("Сначала отправь /start и введи свои данные ✨")
        return

    prompt = (
        f"Ты профессиональный астролог. Пользователь задаёт вопрос. "
        f"Дата рождения: {user['birth_date']}, "
        f"время: {user['birth_time']}, "
        f"место: {user['birth_place']}.\n"
        f"Ответь на вопрос, используя знания астрологии и натальной карты.\n"
        f"Вопрос: {message.text}\n"
        f"Отвечай подробно, но ясно и красиво. Используй эмоджи и выделения жирным шрифтом."
)

    try:
        typing_msg = await bot.send_message(user_id, "✍️ Бот печатает...")
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
        )
        answer = response.choices[0].message.content
        await bot.delete_message(chat_id=user_id, message_id=typing_msg.message_id)
    except Exception as e:
        logging.error(f"Ошибка при запросе к OpenAI: {e}")
        await message.reply("❌ Произошла ошибка при обработке твоего запроса. Попробуй позже.")
        return

    await message.reply(answer, parse_mode="Markdown")
    
@dp.callback_query_handler(lambda c: c.data == 'daily_horoscope')
async def daily_horoscope_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user = user_data.get(user_id)

    try:
        await callback_query.answer("✨ Готовлю твой гороскоп на сегодня...")
    except Exception as e:
        logging.warning(f"Не удалось ответить на callback_query: {e}")

    if not user:
        await bot.send_message(user_id, "Сначала отправь /start и введи свои данные ✨")
        return

    user_first_name = user.get('first_name', 'друг')  # Получаем имя пользователя

    prompt = (
        f"Ты профессиональный астролог.\n"
        f"У пользователя дата рождения: {user['birth_date']}, "
        f"время: {user['birth_time']}, "
        f"место: {user['birth_place']}.\n"
        f"Составь подробный гороскоп на сегодня на основе этих данных.\n"
        f"Используй реальные астрологические факты и тренды дня.\n"
        f"Выделяй важные моменты **жирным шрифтом** и добавляй эмоджи.\n"
        f"Пиши вдохновляюще и ясно."
    )

    try:
        typing_msg = await bot.send_message(user_id, "✍️ Бот печатает гороскоп...")
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
        )
        answer = response.choices[0].message.content
        await bot.delete_message(chat_id=user_id, message_id=typing_msg.message_id)
    except Exception as e:
        logging.error(f"Ошибка при запросе к OpenAI: {e}")
        await bot.send_message(user_id, f"❌ Произошла ошибка при получении гороскопа на сегодня, {user_first_name}.")
        return

    await bot.send_message(user_id, f"🔮 Вот твой гороскоп на сегодня, {user_first_name}:\n{answer}", parse_mode="Markdown", reply_markup=after_horoscope_keyboard)    

# Функция для создания базы данных и таблиц
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)  # Запуск бота
