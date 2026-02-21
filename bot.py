import os
import logging
import sqlite3
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Добавьте этот класс для обработки пингов от Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    
    def log_message(self, format, *args):
        # Отключаем логирование запросов
        pass

# Функция для запуска HTTP сервера на порту Render
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
EMPLOYEES = ["Наринэ", "Катя", "Жанна", "Августина", "Лилит", "Настя", "Ира", "Юля", "Богдан"]

ADMIN_IDS = [402039866, 1078706303]  

# Штрафы по категориям
FINES = {
    50: ["❌ Невыполнение задания", "💔 Порча продукции", "🔧 Порча инвентаря"],
    25: ["⏰ Просрок", "🏷 Отсутствие маркировки", "📅 Продление срока", "📦 Нет упаковки", "🧹 Грязное оборудование", "👎 Нетоварный вид"],
    10: ["👋 Не здороваемся", "🍔 Еда в рабочей зоне", "👕 Личные вещи", "🛒 Пустая зона", "🚪 Не открыта дверь"]
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
        return True
    
    # Также проверяем в базе данных (на случай динамического добавления)
    conn = sqlite3.connect('fines.db')
    c = conn.cursor()
    c.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    return result is not None

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

async def main_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE, text="Главное меню:"):
    """Показывает главное меню с учетом прав пользователя"""
    user_id = update_or_query.effective_user.id if hasattr(update_or_query, 'effective_user') else update_or_query.from_user.id
    
    if is_admin(user_id):
        # Меню для администратора
        keyboard = [
            [InlineKeyboardButton("📝 Добавить штраф", callback_data="add_fine")],
            [InlineKeyboardButton("📊 Проверить штрафы", callback_data="check_fines")],
            [InlineKeyboardButton("✏️ Корректировка штрафов", callback_data="adjust_fines")]
        ]
    else:
        # Меню для обычного пользователя
        keyboard = [
            [InlineKeyboardButton("📊 Проверить штрафы", callback_data="check_fines")]
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
    
    if is_admin(user_id):
        await main_menu(update, context, f"👋 Добро пожаловать, администратор @{username}!")
    else:
        await main_menu(update, context, f"👋 Добро пожаловать, @{username}!\n\nВы можете просматривать штрафы.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    is_admin_user = is_admin(user_id)
    
    # Проверяем права доступа для административных функций
    if not is_admin_user and query.data not in ["check_fines", "main_menu", "no_action", "back_to_fines_list"]:
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
        keyboard = []
        for emp in EMPLOYEES:
            keyboard.append([InlineKeyboardButton(emp, callback_data=f"emp_{emp}")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            "👥 Выберите сотрудника:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("emp_") and is_admin_user:
        employee = query.data[4:]
        context.user_data['employee'] = employee
        keyboard = []
        for amt in FINES.keys():
            keyboard.append([InlineKeyboardButton(f"{amt} баллов", callback_data=f"cat_{amt}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад к сотрудникам", callback_data="add_fine")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"👤 Сотрудник: {employee}\n\n"
            f"💰 Выберите сумму штрафа:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("cat_") and is_admin_user:
        amount = int(query.data[4:])
        context.user_data['amount'] = amount
        employee = context.user_data.get('employee', '')
        keyboard = []
        for i, reason in enumerate(FINES[amount]):
            keyboard.append([InlineKeyboardButton(reason, callback_data=f"reason_{i}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад к суммам", callback_data=f"emp_{employee}")])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"👤 Сотрудник: {employee}\n"
            f"💰 Сумма: {amount} баллов\n\n"
            f"📋 Выберите причину:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("reason_") and is_admin_user:
        idx = int(query.data[7:])
        amount = context.user_data['amount']
        employee = context.user_data['employee']
        reason = FINES[amount][idx]
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
    
    elif query.data == "check_fines":
        # Получаем список сотрудников со штрафами
        employees_with_fines = get_all_employees_with_fines()
        
        if not employees_with_fines:
            text = f"📊 Штрафы за {get_current_month()}\n\n"
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
        
        # Создаем клавиатуру с сотрудниками
        keyboard = []
        for emp in employees_with_fines:
            total = get_employee_total(emp)
            keyboard.append([InlineKeyboardButton(
                f"{emp} — {total} баллов", 
                callback_data=f"view_employee_{emp}"
            )])
        
        # Добавляем навигационные кнопки
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
    
    elif query.data.startswith("view_employee_"):
        employee = query.data[14:]
        
        # Получаем сводку по штрафам сотрудника
        total, reasons_summary = get_employee_fines_summary(employee)
        
        # Формируем текст сообщения
        text = f"👤 **{employee}**\n"
        text += f"📅 Месяц: {get_current_month()}\n"
        text += f"💰 **Общая сумма штрафов: {total} баллов**\n\n"
        
        if reasons_summary:
            text += "📋 **Детализация по причинам:**\n"
            text += "═" * 25 + "\n"
            
            for reason, count, amount in reasons_summary:
                # Эмодзи для разных сумм
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
HEAD
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
        print("Проверьте настройки Environment Variables на Render")
        return
    
    print(f"✅ Токен получен: {token[:10]}...")  # Показываем начало токена для проверки
    
    # Создаем приложение
    app = Application.builder().token(token).build()

    import os
    import traceback # Добавляем модуль для печати полной ошибки
ef631e8fd22905bbf8608941dff1c9c49c433aa1

    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
