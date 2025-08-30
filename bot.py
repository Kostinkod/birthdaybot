import os
import logging
from datetime import datetime, timedelta, time
from pytz import timezone as pytz_tz
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackContext,
    JobQueue,
)

# Настройка журналирования
logging.basicConfig(
    filename='bot.log',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
TZ = pytz_tz('Europe/Berlin')  # Часовой пояс
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"  # Токен вашего бота

# Словарь для хранения дат рождения пользователей (ключ: user_id, значение: объект datetime.date без года)
USERS_BIRTHDAYS = {}

# Словарь для хранения информации о подписках (ключ: chat_id, значение: job_id)
USER_SUBSCRIPTIONS = {}

# Константа состояний для диалога
SETTING_BIRTHDAY = 0

def ru_days(n: int) -> str:
    """
    Возвращает правильное склонение русского слова "день/дня/дней" в зависимости от числа.
    """
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return "дня"
    else:
        return "дней"

def calculate_days_to_birthday(user_birthday: datetime.date, current_date: datetime.date) -> tuple[int, datetime.date]:
    """
    Рассчитывает количество оставшихся дней до следующего дня рождения.
    """
    current_year = current_date.year
    next_birthday = user_birthday.replace(year=current_year)
    
    # Проверяем, наступила ли эта дата в текущем году
    if next_birthday < current_date:
        next_birthday = next_birthday.replace(year=current_year + 1)
    
    remaining_days = (next_birthday - current_date).days
    return remaining_days, next_birthday

# Функция для отправки ежедневного уведомления
async def send_daily_notification(context: CallbackContext) -> None:
    for user_id, user_birthday in USERS_BIRTHDAYS.items():
        current_date = datetime.now(TZ).date()
        days_left, _ = calculate_days_to_birthday(user_birthday, current_date)
        
        # Отправляем уведомление только если остались дни до дня рождения
        if days_left > 0:
            day_word = ru_days(days_left)
            message = f"Пользователь @{context.bot.username}, до Вашего дня рождения осталось: {days_left} {day_word}"
            await context.bot.send_message(chat_id=user_id, text=message)

# Telegram-хэндлеры
async def start(update: Update, context: CallbackContext) -> None:
    """Отправляет приветственное сообщение и список команд."""
    await update.message.reply_text(
        "Привет! Я подсчитываю, сколько осталось до твоего дня рождения.\n"
        "Доступные команды:\n"
        "/birthday — показывает, сколько дней осталось до дня рождения\n"
        "/today — отображает текущую дату\n"
        "/subscribe — ежедневно получать уведомление в 09:00\n"
        "/unsubscribe — отменить получение уведомлений.\n"
        "/setbday — установить свою дату рождения"
    )
    logger.info(f"Команда '/start' выполнена пользователем {update.effective_user.first_name} (ID: {update.effective_user.id}).")

async def birthday_command(update: Update, context: CallbackContext) -> None:
    """Показывает, сколько дней осталось до дня рождения"""
    user_id = update.effective_user.id
    if user_id in USERS_BIRTHDAYS:
        current_date = datetime.now(TZ).date()
        days_left, _ = calculate_days_to_birthday(USERS_BIRTHDAYS[user_id], current_date)
        day_word = ru_days(days_left)
        await update.message.reply_text(f"Дней до дня рождения осталось: {days_left} {day_word}")
    else:
        await update.message.reply_text("Вы ещё не указали дату своего дня рождения. Используйте команду /setbday.")

async def today_command(update: Update, context: CallbackContext) -> None:
    """Отображает текущую дату"""
    now = datetime.now(TZ)
    await update.message.reply_text(now.strftime("%d.%m.%Y"))

async def subscribe_command(update: Update, context: CallbackContext) -> None:
    """Подписывает пользователя на ежедневные уведомления в 09:00"""
    user_id = update.effective_user.id
    if user_id not in USER_SUBSCRIPTIONS:
        # Устанавливаем регулярное задание на отправку уведомления
        job = context.job_queue.run_daily(send_daily_notification, time(hour=9, minute=0, tzinfo=TZ), name=f"{user_id}_subscription")
        USER_SUBSCRIPTIONS[user_id] = job
        await update.message.reply_text("Теперь Вы будете получать ежедневные уведомления в 09:00.")
    else:
        await update.message.reply_text("Вы уже подписаны на уведомления.")

async def unsubscribe_command(update: Update, context: CallbackContext) -> None:
    """Отменяет подписывание пользователя на уведомления"""
    user_id = update.effective_user.id
    if user_id in USER_SUBSCRIPTIONS:
        job = USER_SUBSCRIPTIONS.pop(user_id)
        job.schedule_removal()  # Удаляем регулярное задание
        await update.message.reply_text("Ваше подписывание отменено.")
    else:
        await update.message.reply_text("Вы не были подписаны на уведомления.")

async def ask_for_birthday(update: Update, context: CallbackContext) -> int:
    """Запрашивает у пользователя дату рождения."""
    await update.message.reply_text("Пожалуйста, введите вашу дату рождения в формате ДД.ММ:")
    return SETTING_BIRTHDAY

async def save_birthday(update: Update, context: CallbackContext) -> int:
    """Сохраняет дату рождения пользователя."""
    input_date_str = update.message.text.strip()
    user_id = update.effective_user.id
    try:
        # Разбираем дату без года
        user_birthday_dt = datetime.strptime(input_date_str, '%d.%m').date()
        USERS_BIRTHDAYS[user_id] = user_birthday_dt
        await update.message.reply_text(f"Ваша дата рождения сохранена: {input_date_str}.")
        logger.info(f"Дата рождения пользователя {update.effective_user.first_name} (ID: {update.effective_user.id}) успешно установлена.")
    except ValueError:
        await update.message.reply_text("Ошибка формата даты. Попробуйте снова ввести дату в формате ДД.ММ.")
        return SETTING_BIRTHDAY
    finally:
        return ConversationHandler.END

async def echo_message(update: Update, context: CallbackContext) -> None:
    """Универсальная реакция на входящие сообщения."""
    await update.message.reply_text("Простите, я пока не понимаю этот запрос. Используйте доступные команды (/help)")

# Создаем приложение
app = Application.builder().token(TOKEN).build()
job_queue = app.job_queue  # Получаем доступ к очереди задач

# Регистрация обработчиков
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('setbday', ask_for_birthday),
    ],
    states={
        SETTING_BIRTHDAY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, save_birthday),
        ]
    },
    fallbacks=[]  # Здесь добавьте необходимые обработчики завершения разговора
)

app.add_handler(conv_handler)
app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('birthday', birthday_command))
app.add_handler(CommandHandler('today', today_command))
app.add_handler(CommandHandler('subscribe', subscribe_command))
app.add_handler(CommandHandler('unsubscribe', unsubscribe_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_message))  # Универсальный обработчик сообщений

# Старт приложения
if __name__ == '__main__':
    app.run_polling()
