import os
import logging
import sqlite3
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Добавьте этот класс для обработки пингов от Render (для BotHost не обязателен, но пусть будет)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    
    def log_message(self, format, *args):
        # Отключаем логирование запросов
        pass

# Функция для запуска HTTP сервера (для BotHost не обязательна, но пусть будет)
def run_health_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health check server running on port {port}")
    server.serve_forever()

# Запускаем health check сервер в отдельном потоке
health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Список сотрудников
EMPLOYEES = ["Наринэ", "Катя_К", "Жанна", "Августина", "Лилит", "Настя", "Ира", "Юля", "Катя_С", "Богдан"]

ADMIN_IDS = [402039866, 1078706301]  

# Штрафы по категориям
FINES = {
    50: ["❌ Невыполнение задания", "⛓️‍💥 Порча продукции", "🔪 Порча инвентаря"],
    25: ["🏷 Отсутствие маркировки", "📅 Просрок/Продление срока", "📦 Нет упаковки", "🦠 Грязное оборудование", "👎 Нетоварный вид", "🤢 Хранение продуктов"],
    15: ["👋 Не здороваемся", "🍔/👕 Еда / личн.вещи в раб.зоне", "🙅‍♂️ Зона самообслуж.", "🧹 Крошки/грязь в зале", "🚪 Не открыта вх.дверь", "😣 Прочее"]
}

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS fines 
                 (id INTEGER PRIMARY KEY, employee TEXT, amount INTEGER, 
                  reason TEXT, date TEXT, month TEXT)''')
    
    # Таблица для хранения ID администраторов в БД (на случай, если нужно будет добавлять через бота)
    c.execute('''CREATE TABLE IF NOT EXISTS admins 
                 (user_id INTEGER PRIMARY KEY, username TEXT, added_date TEXT)''')
    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    # Проверяем по списку ADMIN_IDS
    if user_id in ADMIN_IDS:
        print(f"✅ Админ {user_id} найден в списке ADMIN_IDS")
        return True
    
    print(f"❌ Пользователь {user_id} НЕ в списке ADMIN_IDS: {ADMIN_IDS}")
    
    # Также проверяем в базе данных (на случай динамического добавления)
    try:
        conn = sqlite3.connect('fines.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        
        if result:
            print(f"✅ Админ {user_id} найден в БД")
            return True
        else:
            print(f"❌ Админ {user_id} НЕ найден в БД")
    except Exception as e:
        print(f"Ошибка при проверке БД: {e}")
    
    return False

def get_current_month():
    return datetime.now().strftime("%Y-%m")

def add_fine(employee, amount, reason):
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    c.execute('INSERT INTO fines (employee, amount, reason, date, month) VALUES (?,?,?,?,?)',
              (employee, amount, reason, datetime.now().strftime("%Y-%m-%d %H:%M"), get_current_month()))
    conn.commit()
    conn.close()

def remove_last_fine(employee):
    """Удаляет последний штраф сотрудника за текущий месяц"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    current_month = get_current_month()
    
    c.execute('''
        SELECT id, amount, reason FROM fines 
        WHERE month=? AND employee=? 
        ORDER BY date DESC LIMIT 1
    ''', (current_month, employee))
    
    last_fine = c.fetchone()
    
    if last_fine:
        c.execute('DELETE FROM fines WHERE id=?', (last_fine[0],))
        conn.commit()
        conn.close()
        return last_fine
    
    conn.close()
    return None

def get_employee_total(employee):
    """Получает общую сумму штрафов сотрудника за текущий месяц"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    current_month = get_current_month()
    
    c.execute('SELECT SUM(amount) FROM fines WHERE month=? AND employee=?', (current_month, employee))
    total = c.fetchone()[0]
    conn.close()
    
    return total if total else 0

def get_employee_fines_list(employee):
    """Получает список всех штрафов сотрудника за текущий месяц"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    current_month = get_current_month()
    
    c.execute('''
        SELECT id, amount, reason, date FROM fines 
        WHERE month=? AND employee=? 
        ORDER BY date DESC
    ''', (current_month, employee))
    
    results = c.fetchall()
    conn.close()
    
    return results

def get_employee_fines_summary(employee):
    """Получает сводку штрафов сотрудника с группировкой по причинам"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    current_month = get_current_month()
    
    # Получаем общую сумму
    c.execute('SELECT SUM(amount) FROM fines WHERE month=? AND employee=?', (current_month, employee))
    total = c.fetchone()[0] or 0
    
    # Получаем группировку по причинам с количеством
    c.execute('''
        SELECT reason, COUNT(*) as count, SUM(amount) as total_amount 
        FROM fines 
        WHERE month=? AND employee=? 
        GROUP BY reason 
        ORDER BY total_amount DESC
    ''', (current_month, employee))
    
    reasons_summary = c.fetchall()
    conn.close()
    
    return total, reasons_summary

def delete_specific_fine(fine_id):
    """Удаляет конкретный штраф по ID"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    
    c.execute('DELETE FROM fines WHERE id=?', (fine_id,))
    conn.commit()
    conn.close()

def get_all_employees_with_fines():
    """Получает список всех сотрудников, у которых есть штрафы в текущем месяце"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    current_month = get_current_month()
    
    c.execute('''
        SELECT DISTINCT employee FROM fines 
        WHERE month=? 
        ORDER BY employee
    ''', (current_month,))
    
    results = [row[0] for row in c.fetchall()]
    conn.close()
    
    return results

def get_monthly_fines():
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    c.execute('SELECT employee, SUM(amount) FROM fines WHERE month=? GROUP BY employee', (get_current_month(),))
    results = dict(c.fetchall())
    conn.close()
    return results

# ============= НОВЫЕ ФУНКЦИИ ДЛЯ АРХИВА МЕСЯЦЕВ =============

def get_available_months():
    """Получает список всех месяцев, за которые есть штрафы"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    c.execute('SELECT DISTINCT month FROM fines ORDER BY month DESC')
    results = [row[0] for row in c.fetchall()]
    conn.close()
    return results

def get_monthly_fines_by_month(month):
    """Получает штрафы за конкретный месяц"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    c.execute('SELECT employee, SUM(amount) FROM fines WHERE month=? GROUP BY employee', (month,))
    results = dict(c.fetchall())
    conn.close()
    return results

def get_employee_fines_summary_by_month(employee, month):
    """Получает сводку штрафов сотрудника за конкретный месяц"""
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    
    # Получаем общую сумму
    c.execute('SELECT SUM(amount) FROM fines WHERE month=? AND employee=?', (month, employee))
    total = c.fetchone()[0] or 0
    
    # Получаем группировку по причинам
    c.execute('''
        SELECT reason, COUNT(*) as count, SUM(amount) as total_amount 
        FROM fines 
        WHERE month=? AND employee=? 
        GROUP BY reason 
        ORDER BY total_amount DESC
    ''', (month, employee))
    
    reasons_summary = c.fetchall()
    conn.close()
    
    return total, reasons_summary

def safe_callback(text: str) -> str:
    """Заменяет пробелы и специальные символы на _ для callback_data"""
    return text.replace(' ', '_').replace('/', '_').replace('\\', '_')

# ============================================================

async def main_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE, text="Главное меню:"):
    """Показывает главное меню с учетом прав пользователя"""
    user_id = update_or_query.effective_user.id if hasattr(update_or_query, 'effective_user') else update_or_query.from_user.id
    
    if is_admin(user_id):
        # Меню для администратора
        keyboard = [
            [InlineKeyboardButton("📝 Добавить штраф", callback_data="add_fine")],
            [InlineKeyboardButton("📊 Текущий месяц", callback_data="check_fines")],
            [InlineKeyboardButton("📅 Архив месяцев", callback_data="show_months")],
            [InlineKeyboardButton("✏️ Корректировка штрафов", callback_data="adjust_fines")]
        ]
    else:
        # Меню для обычного пользователя
        keyboard = [
            [InlineKeyboardButton("📊 Текущий месяц", callback_data="check_fines")],
            [InlineKeyboardButton("📅 Архив месяцев", callback_data="show_months")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(text, reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    
    logger.info(f"Пользователь {user_id} (@{username}) запустил бота")
    
    # ДИАГНОСТИКА
    print(f"START: user_id={user_id}, username={username}")
    print(f"START: ADMIN_IDS={ADMIN_IDS}")
    print(f"START: is_admin={is_admin(user_id)}")
    
    if is_admin(user_id):
        await main_menu(update, context, f"👋 Добро пожаловать, администратор @{username}!")
    else:
        await main_menu(update, context, f"👋 Добро пожаловать, @{username}!\n\nВы можете просматривать штрафы.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # ДИАГНОСТИКА
    print(f"🔍 CALLBACK: data='{query.data}'")
    print(f"🔍 is_admin_user={is_admin(query.from_user.id)}")
    
    user_id = query.from_user.id
    is_admin_user = is_admin(user_id)
    
    # Проверяем права доступа для административных функций
    if not is_admin_user and query.data not in ["check_fines", "main_menu", "no_action", "back_to_fines_list", "show_months"]:
        await query.edit_message_text(
            "⛔ У вас нет прав для выполнения этого действия.\n\n"
            "Только администраторы могут добавлять и корректировать штрафы.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ В главное меню", callback_data="main_menu")
            ]])
        )
        return
    
    if query.data == "main_menu":
        await main_menu(query, context)
    
    elif query.data == "add_fine" and is_admin_user:
        # Шаг 1: Выбор сотрудника
        keyboard = []
        for emp in EMPLOYEES:
            safe_emp = safe_callback(emp)
            keyboard.append([InlineKeyboardButton(emp, callback_data=f"emp_fine_{safe_emp}")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            "👥 Выберите сотрудника:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("emp_fine_") and is_admin_user:
        # Шаг 2: Выбор нарушения
        employee_raw = query.data[9:]
        
        # Восстанавливаем оригинальное имя
        employee = None
        for emp in EMPLOYEES:
            if safe_callback(emp) == employee_raw:
                employee = emp
                break
        
        if not employee:
            employee = employee_raw.replace('_', ' ')
        
        context.user_data['employee'] = employee
        
        # Собираем все нарушения в один список с индексами
        keyboard = []
        fine_index = 0
        for amount, reasons in FINES.items():
            for reason in reasons:
                keyboard.append([InlineKeyboardButton(
                    f"{reason} ({amount} баллов)", 
                    callback_data=f"fine_{fine_index}"
                )])
                fine_index += 1
        
        keyboard.append([InlineKeyboardButton("◀️ Назад к сотрудникам", callback_data="add_fine")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"👤 Сотрудник: {employee}\n\n"
            f"📋 Выберите нарушение:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("fine_") and is_admin_user:
        # Шаг 3: Добавление штрафа по индексу
        fine_index = int(query.data[5:])
        
        # Находим нарушение по индексу
        all_fines = []
        for amount, reasons in FINES.items():
            for reason in reasons:
                all_fines.append((amount, reason))
        
        amount, reason = all_fines[fine_index]
        employee = context.user_data.get('employee', '')
        
        add_fine(employee, amount, reason)
        
        keyboard = [
            [InlineKeyboardButton("📝 Добавить ещё штраф", callback_data="add_fine")],
            [InlineKeyboardButton("✏️ Корректировка штрафов", callback_data="adjust_fines")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]
        ]
        
        new_total = get_employee_total(employee)
        
        await query.edit_message_text(
            f"✅ Штраф успешно добавлен!\n\n"
            f"👤 Сотрудник: {employee}\n"
            f"💰 Штраф: {amount} баллов\n"
            f"📋 Причина: {reason}\n"
            f"📅 Месяц: {get_current_month()}\n"
            f"💯 Всего у сотрудника: {new_total} баллов",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "adjust_fines" and is_admin_user:
        # Получаем список сотрудников, у которых есть штрафы
        employees_with_fines = get_all_employees_with_fines()
        
        if not employees_with_fines:
            keyboard = [[InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]]
            await query.edit_message_text(
                "✏️ Корректировка штрафов\n\n"
                "❌ Нет сотрудников со штрафами в текущем месяце",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Показываем список всех сотрудников со штрафами
        keyboard = []
        for emp in employees_with_fines:
            total = get_employee_total(emp)
            keyboard.append([InlineKeyboardButton(
                f"{emp} (👤 {total} баллов)", 
                callback_data=f"adjust_emp_{emp}"
            )])
        
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            "✏️ Корректировка штрафов\n\n"
            "Выберите сотрудника для корректировки:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("adjust_emp_") and is_admin_user:
        employee = query.data[11:]
        context.user_data['adjust_employee'] = employee
        
        fines_list = get_employee_fines_list(employee)
        total = get_employee_total(employee)
        
        keyboard = []
        
        # Добавляем кнопки для каждого штрафа
        for fine_id, amount, reason, date in fines_list:
            date_short = date.split()[0]
            short_reason = reason if len(reason) <= 25 else reason[:22] + "..."
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 {amount} баллов - {short_reason} ({date_short})", 
                    callback_data=f"delete_fine_{fine_id}"
                )
            ])
        
        # Кнопка для удаления последнего штрафа
        if fines_list:
            keyboard.append([InlineKeyboardButton("⏪ Удалить последний штраф", callback_data=f"delete_last_{employee}")])
        
        keyboard.append([InlineKeyboardButton("◀️ Назад к списку сотрудников", callback_data="adjust_fines")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"✏️ Корректировка штрафов: {employee}\n"
            f"💰 Текущая сумма: {total} баллов\n"
            f"📋 Количество штрафов: {len(fines_list)}\n\n"
            f"Выберите штраф для удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("delete_last_") and is_admin_user:
        employee = query.data[12:]
        
        last_fine = remove_last_fine(employee)
        
        if last_fine:
            fine_id, amount, reason = last_fine
            new_total = get_employee_total(employee)
            
            keyboard = [
                [InlineKeyboardButton("✏️ Продолжить корректировку", callback_data=f"adjust_emp_{employee}")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]
            ]
            
            await query.edit_message_text(
                f"✅ Последний штраф удален!\n\n"
                f"👤 Сотрудник: {employee}\n"
                f"💰 Удалено: {amount} баллов\n"
                f"📋 Причина: {reason}\n"
                f"💯 Новая сумма: {new_total} баллов",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            keyboard = [
                [InlineKeyboardButton("◀️ Назад", callback_data=f"adjust_emp_{employee}")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]
            ]
            
            await query.edit_message_text(
                f"❌ У сотрудника {employee} нет штрафов для удаления",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    elif query.data.startswith("delete_fine_") and is_admin_user:
        fine_id = int(query.data[12:])
        
        conn = sqlite3.connect('fines.db')
        c = conn.cursor()
        c.execute('SELECT employee, amount, reason FROM fines WHERE id=?', (fine_id,))
        fine_info = c.fetchone()
        conn.close()
        
        if fine_info:
            employee, amount, reason = fine_info
            delete_specific_fine(fine_id)
            new_total = get_employee_total(employee)
            
            keyboard = [
                [InlineKeyboardButton("✏️ Продолжить корректировку", callback_data=f"adjust_emp_{employee}")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]
            ]
            
            await query.edit_message_text(
                f"✅ Штраф удален!\n\n"
                f"👤 Сотрудник: {employee}\n"
                f"💰 Удалено: {amount} баллов\n"
                f"📋 Причина: {reason}\n"
                f"💯 Новая сумма: {new_total} баллов",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                f"❌ Штраф не найден или уже был удален",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")
                ]])
            )
    
    # ============= ОБНОВЛЕННЫЙ ОБРАБОТЧИК check_fines =============
    elif query.data == "check_fines":
        # Получаем список сотрудников со штрафами за текущий месяц
        current = get_current_month()
        employees_with_fines = get_all_employees_with_fines()
        
        if not employees_with_fines:
            text = f"📊 Текущий месяц ({current})\n\n"
            text += "За текущий месяц штрафов нет."
            
            # Для админов добавляем кнопку добавления
            if is_admin_user:
                keyboard = [
                    [InlineKeyboardButton("📝 Добавить штраф", callback_data="add_fine")],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]
                ]
            else:
                keyboard = [[InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]]
            
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return
        
        # Форматируем название месяца
        year, month_num = current.split('-')
        month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                      "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        month_name = month_names[int(month_num) - 1]
        
        # Создаем клавиатуру с сотрудниками
        keyboard = []
        for emp in employees_with_fines:
            total = get_employee_total(emp)
            keyboard.append([InlineKeyboardButton(
                f"{emp} — {total} баллов", 
                callback_data=f"view_employee_{emp}"
            )])
        
        # Добавляем навигационные кнопки
        nav_buttons = []
        if is_admin_user:
            nav_buttons.append(InlineKeyboardButton("📝 Добавить штраф", callback_data="add_fine"))
            nav_buttons.append(InlineKeyboardButton("✏️ Корректировка", callback_data="adjust_fines"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("📅 Архив месяцев", callback_data="show_months")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"📊 ТЕКУЩИЙ МЕСЯЦ: {month_name.upper()} {year}\n\n"
            f"Выберите сотрудника для просмотра детальной информации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ============= ОБНОВЛЕННЫЙ ОБРАБОТЧИК view_employee_ =============
    elif query.data.startswith("view_employee_"):
        employee = query.data[14:]
        current = get_current_month()
        
        # Получаем сводку по штрафам сотрудника за текущий месяц
        total, reasons_summary = get_employee_fines_summary(employee)
        
        # Форматируем название месяца
        year, month_num = current.split('-')
        month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                      "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        month_name = month_names[int(month_num) - 1]
        
        text = f"👤 **{employee}**\n"
        text += f"📅 {month_name} {year} (текущий месяц)\n"
        text += f"💰 **Общая сумма штрафов: {total} баллов**\n\n"
        
        if reasons_summary:
            text += "📋 **Детализация по причинам:**\n"
            text += "═" * 25 + "\n"
            
            for reason, count, amount in reasons_summary:
                if amount >= 50:
                    emoji = "🔴"
                elif amount >= 25:
                    emoji = "🟠"
                else:
                    emoji = "🟡"
                
                text += f"{emoji} **{reason}**\n"
                text += f"   └─ {count} штраф(ов) на {amount} баллов\n"
            
            text += "═" * 25 + "\n"
        else:
            text += "❌ Нет штрафов за текущий месяц\n"
        
        # Кнопки навигации
        keyboard = [
            [InlineKeyboardButton("◀️ Назад к списку", callback_data="check_fines")],
            [InlineKeyboardButton("📅 Архив месяцев", callback_data="show_months")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]
        ]
        
        # Для админов добавляем кнопку корректировки
        if is_admin(user_id):
            keyboard.insert(0, [InlineKeyboardButton("✏️ Корректировать штрафы", callback_data=f"adjust_emp_{employee}")])
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    # ============= НОВЫЙ ОБРАБОТЧИК show_months =============
    elif query.data == "show_months":
        # Показываем список доступных месяцев
        months = get_available_months()
        current = get_current_month()
        
        if not months:
            await query.edit_message_text(
                "📅 Архив пуст\n\n"
                "Пока нет записей о штрафах.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        keyboard = []
        for month in months:
            # Форматируем месяц для отображения (YYYY-MM -> Месяц ГГГГ)
            year, month_num = month.split('-')
            month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
            month_name = month_names[int(month_num) - 1]
            display_text = f"{month_name} {year}"
            
            # Добавляем отметку для текущего месяца
            if month == current:
                display_text += " (текущий)"
                
            keyboard.append([InlineKeyboardButton(
                display_text,
                callback_data=f"month_{month}"
            )])
        
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            "📅 Выберите месяц для просмотра:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ============= НОВЫЙ ОБРАБОТЧИК month_ =============
    elif query.data.startswith("month_"):
        # Показываем список сотрудников за выбранный месяц
        month = query.data[6:]
        monthly_fines = get_monthly_fines_by_month(month)
        
        if not monthly_fines:
            await query.edit_message_text(
                f"📊 Штрафы за {month}\n\n"
                f"За этот месяц штрафов нет.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад к месяцам", callback_data="show_months"),
                    InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")
                ]])
            )
            return
        
        # Форматируем название месяца для заголовка
        year, month_num = month.split('-')
        month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                      "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        month_name = month_names[int(month_num) - 1]
        
        text = f"📊 ШТРАФЫ ЗА {month_name.upper()} {year}\n"
        text += "═" * 25 + "\n\n"
        
        # Сортируем по сумме (от большего к меньшему)
        sorted_fines = sorted(monthly_fines.items(), key=lambda x: x[1], reverse=True)
        
        keyboard = []
        for emp, total in sorted_fines:
            text += f"👤 {emp}: {total} баллов\n"
            # Добавляем кнопку для просмотра деталей
            safe_emp = safe_callback(emp)
            keyboard.append([InlineKeyboardButton(
                f"👤 {emp} — {total} баллов",
                callback_data=f"month_emp_{month}_{safe_emp}"
            )])
        
        keyboard.append([InlineKeyboardButton("◀️ Назад к месяцам", callback_data="show_months")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            text + "\n" + "Выберите сотрудника для детализации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ============= НОВЫЙ ОБРАБОТЧИК month_emp_ =============
    elif query.data.startswith("month_emp_"):
        # Показываем детализацию штрафов сотрудника за выбранный месяц
        parts = query.data.split('_')
        month = parts[2]
        employee_raw = '_'.join(parts[3:])
        
        # Восстанавливаем оригинальное имя сотрудника
        employee = employee_raw.replace('_', ' ')
        
        total, reasons_summary = get_employee_fines_summary_by_month(employee, month)
        
        # Форматируем название месяца
        year, month_num = month.split('-')
        month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                      "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        month_name = month_names[int(month_num) - 1]
        
        text = f"👤 **{employee}**\n"
        text += f"📅 {month_name} {year}\n"
        text += f"💰 **Общая сумма штрафов: {total} баллов**\n\n"
        
        if reasons_summary:
            text += "📋 **Детализация по причинам:**\n"
            text += "═" * 25 + "\n"
            
            for reason, count, amount in reasons_summary:
                if amount >= 50:
                    emoji = "🔴"
                elif amount >= 25:
                    emoji = "🟠"
                else:
                    emoji = "🟡"
                
                text += f"{emoji} **{reason}**\n"
                text += f"   └─ {count} штраф(ов) на {amount} баллов\n"
            
            text += "═" * 25 + "\n"
        else:
            text += "❌ Нет штрафов за этот месяц\n"
        
        keyboard = [
            [InlineKeyboardButton("◀️ Назад к сотрудникам", callback_data=f"month_{month}")],
            [InlineKeyboardButton("◀️ Назад к месяцам", callback_data="show_months")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "back_to_fines_list":
        # Возврат к списку сотрудников со штрафами
        employees_with_fines = get_all_employees_with_fines()
        
        keyboard = []
        for emp in employees_with_fines:
            total = get_employee_total(emp)
            keyboard.append([InlineKeyboardButton(
                f"{emp} — {total} баллов", 
                callback_data=f"view_employee_{emp}"
            )])
        
        if is_admin_user:
            keyboard.append([
                InlineKeyboardButton("📝 Добавить штраф", callback_data="add_fine"),
                InlineKeyboardButton("✏️ Корректировка", callback_data="adjust_fines")
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"📊 ШТРАФЫ ЗА {get_current_month()}\n\n"
            f"Выберите сотрудника для просмотра детальной информации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "no_action":
        await query.answer("Нет доступных действий")

def main():
    # Инициализация БД
    init_db()
    
    # Вывод информации об администраторах
    print("=" * 50)
    print("ВАЖНО: Не забудьте заменить ADMIN_IDS на реальные ID!")
    print("Как получить ID: напишите боту @userinfobot")
    print("Текущие ID администраторов:", ADMIN_IDS)
    print("=" * 50)
    
    # Получаем токен из переменных окружения
    token = os.environ.get('BOT_TOKEN')
    
    if not token:
        print("❌ ОШИБКА: BOT_TOKEN не найден в переменных окружения!")
        print("Проверьте настройки Environment Variables на Render/BotHost")
        return
    
    print(f"✅ Токен получен: {token[:10]}...")  # Показываем начало токена для проверки
    
    # Создаем приложение
    app = Application.builder().token(token).build()

    # Добавляем обработчики (с правильным отступом!)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()