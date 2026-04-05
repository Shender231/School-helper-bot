import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telebot import types
import threading
import time
import os
import datetime
from dotenv import load_dotenv

# --- НАСТРОЙКИ ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
JSON_FILE = 'creds.json'
SPREADSHEET_KEY = "1vJs5tMpaYOsbb5rncrBvihGKvOmIUGCePGTsvBMGua8"
SPREADSHEET_FOR_MILK_KEY = "1LrUiy5UmREhok0Vj4w78idwVbTVqN7zVYe-OROc4DqY"
SPREADSHEET_FOR_MEAT_KEY = "1e4kIqjkbr7i86AtgTWvuR47aDJSOcHweDpcLRzZ4yBs"

# База данных пользователей
if not os.path.exists("users.txt"):
    with open("users.txt", "w") as f: pass

# Конфиг расписания
DAYS_CONFIG_STABLE = {
    "Пн": {"rows": "6:13", "name": "Понедельник"},
    "Вт": {"rows": "17:25", "name": "Вторник"},
    "Ср": {"rows": "29:36", "name": "Среду"},
    "Чт": {"rows": "40:47", "name": "Четверг"},
    "Пт": {"rows": "51:58", "name": "Пятницу"},
    "Сб": {"rows": "62:69", "name": "Субботу"}
}
CHANGED_SCAN_CELLS = ["A5", "A16", "A25", "A36", "A47", "A58"]
CHANGED_ROWS = ["6:14", "17:23", "26:34", "37:45", "48:56", "59:67"]

# Конфиг строк меню
MENU_ROWS = {
    "Понедельник": "3:6",
    "Вторник": "8:11",
    "Среда": "13:16",
    "Четверг": "18:21",
    "Пятница": "23:26"
}

# --- ПОДКЛЮЧЕНИЕ ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
client = gspread.authorize(creds)

spreadsheet = client.open_by_key(SPREADSHEET_KEY)
sheet1 = spreadsheet.get_worksheet(0)
sheet2 = spreadsheet.get_worksheet(1)

ss_milk = client.open_by_key(SPREADSHEET_FOR_MILK_KEY)
sheet_milk1 = ss_milk.get_worksheet(0)
sheet_milk2 = ss_milk.get_worksheet(1)

ss_meat = client.open_by_key(SPREADSHEET_FOR_MEAT_KEY)
sheet_meat1 = ss_meat.get_worksheet(0)
sheet_meat2 = ss_meat.get_worksheet(1)

bot = telebot.TeleBot(TOKEN)


# --- ЛОГИКА МЕНЮ ---
def get_menu_data(day_name, menu_type, target_date):
    week_of_year = target_date.isocalendar()[1]
    week_cycle = (week_of_year % 4) or 4

    if menu_type == "milk":
        if week_cycle in [1, 2]:
            sheet = sheet_milk1
            cols = ["A", "D", "E"] if week_cycle == 1 else ["A", "G", "H"]
        else:
            sheet = sheet_milk2
            cols = ["A", "B", "C"] if week_cycle == 3 else ["A", "E", "F"]
    else:  # meat
        if week_cycle in [1, 2]:
            sheet = sheet_meat1
            cols = ["A", "B", "C"] if week_cycle == 1 else ["A", "E", "F"]
        else:
            sheet = sheet_meat2
            cols = ["A", "D", "E"] if week_cycle == 3 else ["A", "G", "H"]

    rows_range = MENU_ROWS.get(day_name)
    if not rows_range: return "❌ Меню на этот день не найдено."

    try:
        start_row, end_row = rows_range.split(":")
        cell_ranges = [f"{cols[0]}{start_row}:{cols[0]}{end_row}",
                       f"{cols[1]}{start_row}:{cols[1]}{end_row}",
                       f"{cols[2]}{start_row}:{cols[2]}{end_row}"]

        batch_data = sheet.batch_get(cell_ranges)
        names, weights, infos = batch_data[0], batch_data[1], batch_data[2]

        m_label = "🥛 МОЛОЧНОЕ" if menu_type == "milk" else "🥩 МЯСНОЕ"
        res = f"{m_label} | *{day_name}*\n(Цикл: неделя {week_cycle})\n\n"

        found = False
        for i in range(len(names)):
            dish = names[i][0].replace('\n', ' ').strip() if i < len(names) and names[i] else ""
            if not dish: continue

            weight = weights[i][0].strip() if i < len(weights) and weights[i] else "?"
            info = infos[i][0].strip() if i < len(infos) and infos[i] else ""
            res += f"🔸 *{dish}*\n└ `{weight} гр.` | `{info}`\n\n"
            found = True

        return res if found else "❌ Данные в таблице отсутствуют."
    except Exception as e:
        return f"❌ Ошибка загрузки: {e}"


# --- РАСПИСАНИЕ И УВЕДОМЛЕНИЯ ---
def get_available_changes():
    found_days = {}
    try:
        values = sheet2.batch_get(CHANGED_SCAN_CELLS)
        for i, val in enumerate(values):
            if val and val[0] and val[0][0].strip():
                text = val[0][0].strip().lower()
                day_key = None
                if "пон" in text:
                    day_key = "Пн"
                elif "вто" in text:
                    day_key = "Вт"
                elif "сре" in text:
                    day_key = "Ср"
                elif "чет" in text:
                    day_key = "Чт"
                elif "пят" in text:
                    day_key = "Пт"
                elif "суб" in text:
                    day_key = "Сб"
                if day_key: found_days[day_key] = {"rows": CHANGED_ROWS[i], "name": text.capitalize()}
        return found_days
    except:
        return {}


def get_schedule(class_name, day_key, is_changed=False):
    columns = {
        "5А": "N", "5Б": "Q", "5В": "T", "6А": "W", "6Б": "Z", "6В": "AC",
        "7А": "AF", "7Б": "AI", "8А": "AL", "8Б": "AO", "9А": "AR", "9Б": "AU",
        "10А": {"cols": ["AX", "AY"], "labels": ["ФИЗ", "ИНФ"]},
        "10Б": {"cols": ["BB", "BC"], "labels": ["ХБ", "ГУМ"]},
        "11А": {"cols": ["BF", "BG"], "labels": ["ФИЗ", "ИНФ"]},
        "11Б": {"cols": ["BJ", "BK"], "labels": ["ХБ", "СОЦ"]},
    }
    if is_changed:
        changes = get_available_changes()
        if day_key not in changes: return "❌ Данные пропали."
        day_info, current_sheet = changes[day_key], sheet2
    else:
        day_info, current_sheet = DAYS_CONFIG_STABLE.get(day_key), sheet1

    rows, col_info = day_info["rows"], columns.get(class_name)
    times = current_sheet.get(f"B{rows}")
    if isinstance(col_info, dict):
        header = f"🔹 *{col_info['labels'][0]} / {col_info['labels'][1]}*\n"
        c1, c2 = current_sheet.get(f"{col_info['cols'][0]}{rows}"), current_sheet.get(f"{col_info['cols'][1]}{rows}")
    else:
        header, c1, c2 = "", current_sheet.get(f"{col_info}{rows}"), None

    res = f"📋 *{'ИЗМЕНЁННОЕ' if is_changed else 'Основное'}* {class_name} на {day_info['name']}\n{header}\n"
    split_subs = ["черч", "англ.яз", "инф", "физ", "геом", "био", "право", "пр.био", "пр.хим", "алг", "хим", "эколог",
                  "пр.физ", "кит.яз", "ВиС", "пр. англ.яз", "рзпп", "пр.мат", "общ", "истор"]

    for i in range(len(times)):
        t_val = times[i][0].strip() if i < len(times) and times[i] else "--:--"
        l1 = c1[i][0].strip() if i < len(c1) and c1[i] else ""
        if c2:
            l2 = c2[i][0].strip() if i < len(c2) and c2[i] else ""
            if not l1 and not l2:
                f_l = "----"
            elif l1 == l2:
                f_l = l1
            elif l1 and not l2:
                l1_c = l1.lower().replace(".", "").strip()
                is_s = any(m.replace(".", "").strip() == l1_c for m in split_subs) or "англ" in l1_c or "инф" in l1_c
                f_l = f"{l1} / ----" if is_s else l1
            elif not l1 and l2:
                f_l = f"---- / {l2}"
            else:
                f_l = f"{l1} / {l2}"
        else:
            f_l = l1 if l1 else "----"
        res += f"▫️ `{t_val}` — {f_l}\n"
    return res


def save_user(uid):
    with open("users.txt", "r+") as f:
        u = f.read().splitlines()
        if str(uid) not in u: f.seek(0, 2); f.write(str(uid) + "\n")


def check_updates():
    last = list(get_available_changes().keys())
    while True:
        try:
            curr = get_available_changes()
            new = [d for d in curr.keys() if d not in last]
            if new:
                with open("users.txt", "r") as f:
                    uids = f.read().splitlines()
                for uid in uids:
                    try:
                        bot.send_message(uid, f"🔔 *Новые изменения!* На дни: {', '.join(new)}.", parse_mode="Markdown")
                    except:
                        pass
            last = list(curr.keys())
        except:
            pass
        time.sleep(600)


threading.Thread(target=check_updates, daemon=True).start()


# --- ОБРАБОТЧИКИ РАСПИСАНИЯ---
@bot.message_handler(commands=['start'])
def start(message):
    save_user(message.chat.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📅 Расписание", "📝 Изменённое расписание")
    markup.add("🍔 Меню")
    bot.send_message(message.chat.id, "Привет! Выбери раздел:", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text in ["📅 Расписание", "📝 Изменённое расписание"])
def choose_class(message):
    is_ch = (message.text == "📝 Изменённое расписание")
    if is_ch and not get_available_changes():
        return bot.send_message(message.chat.id, "✅ Изменений пока нет.")
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=4)
    classes = ["5А", "5Б", "5В", "6А", "6Б", "6В", "7А", "7Б", "8А", "8Б", "9А", "9Б", "10А", "10Б", "11А", "11Б"]
    markup.add(*classes, "Назад")
    msg = bot.send_message(message.chat.id, "Выбери класс:", reply_markup=markup)
    bot.register_next_step_handler(msg, lambda m: process_class(m, is_ch))


def process_class(message, is_ch):
    if message.text == "Назад": return start(message)
    if message.text not in ["5А", "5Б", "5В", "6А", "6Б", "6В", "7А", "7Б", "8А", "8Б", "9А", "9Б", "10А", "10Б", "11А",
                            "11Б"]:
        return start(message)
    show_days(message, message.text, is_ch)


def show_days(message, cls, is_ch):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if is_ch:
        days = list(get_available_changes().keys())
        markup.add(*days)
    else:
        markup.add("Пн", "Вт", "Ср", "Чт", "Пт", "Сб")
    markup.add("Сменить класс", "Назад")
    msg = bot.send_message(message.chat.id, f"📍 {cls} | Выбери день:", reply_markup=markup)
    bot.register_next_step_handler(msg, lambda m: process_day(m, cls, is_ch))


def process_day(message, cls, is_ch):
    if message.text == "Сменить класс": return choose_class(message)
    if message.text == "Назад": return start(message)
    try:
        res = get_schedule(cls, message.text, is_ch)
        bot.send_message(message.chat.id, res, parse_mode="Markdown")
        show_days(message, cls, is_ch)
    except:
        show_days(message, cls, is_ch)


# --- ОБРАБОТЧИКИ МЕНЮ ---
@bot.message_handler(func=lambda m: m.text == "🍔 Меню")
def menu_init(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🥛 Молочное меню", "🥩 Мясное меню")
    markup.add("Назад")
    msg = bot.send_message(message.chat.id, "Какое меню показать?", reply_markup=markup)
    bot.register_next_step_handler(msg, menu_type_selected)


def menu_type_selected(message):
    if message.text == "Назад": return start(message)
    if message.text not in ["🥛 Молочное меню", "🥩 Мясное меню"]:
        msg = bot.send_message(message.chat.id, "Используй кнопки.")
        bot.register_next_step_handler(msg, menu_type_selected)
        return
    m_type = "milk" if "Молочное" in message.text else "meat"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⬅️ Вчера", "⏺ Сегодня", "➡️ Завтра")
    markup.add("Назад")
    msg = bot.send_message(message.chat.id, "На какой день показать?", reply_markup=markup)
    bot.register_next_step_handler(msg, lambda m: process_menu_final(m, m_type))


def process_menu_final(message, m_type):
    if message.text == "Назад": return menu_init(message)
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    now = datetime.datetime.now()
    if "Вчера" in message.text:
        target = now - datetime.timedelta(days=1)
    elif "Сегодня" in message.text:
        target = now
    elif "Завтра" in message.text:
        target = now + datetime.timedelta(days=1)
    else:
        msg = bot.send_message(message.chat.id, "Используй кнопки выбора дня.")
        bot.register_next_step_handler(msg, lambda m: process_menu_final(m, m_type))
        return

    day_name = days_ru[target.weekday()]
    if target.weekday() > 4:
        bot.send_message(message.chat.id, f"🏠 {day_name} — выходной.")
        msg = bot.send_message(message.chat.id, "Выбери другой день:", reply_markup=message.reply_markup)
        bot.register_next_step_handler(msg, lambda m: process_menu_final(m, m_type))
        return

    res = get_menu_data(day_name, m_type, target)
    bot.send_message(message.chat.id, res, parse_mode="Markdown")
    msg = bot.send_message(message.chat.id, "Посмотреть другой день?", reply_markup=message.reply_markup)
    bot.register_next_step_handler(msg, lambda m: process_menu_final(m, m_type))


print("Бот запущен...")
bot.polling(none_stop=True)