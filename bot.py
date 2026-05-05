import logging
import asyncio
from datetime import date, datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()

FLAME_EMOJIS = {
    0: "💀", 1: "🌱", 3: "🔥", 7: "🔥🔥", 14: "🔥🔥🔥",
    30: "⚡🔥", 60: "💥🔥", 100: "👑🔥", 365: "🌟👑🔥"
}

def get_flame_emoji(streak: int) -> str:
    emoji = "💀"
    for days, em in sorted(FLAME_EMOJIS.items()):
        if streak >= days:
            emoji = em
    return emoji

def get_streak_title(streak: int) -> str:
    if streak == 0: return "Огонёк погас 💀"
    if streak < 3: return "Начало пути"
    if streak < 7: return "Горим!"
    if streak < 14: return "Неделя огня!"
    if streak < 30: return "Не остановить!"
    if streak < 60: return "Месяц вместе 🎉"
    if streak < 100: return "Легенды!"
    if streak < 365: return "Нереально!"
    return "БОГИ ОГНЯ 👑"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_user(user.id, user.username or "", user.first_name or "")

    keyboard = [
        [InlineKeyboardButton("👫 Мои друзья", callback_data="friends_list"),
         InlineKeyboardButton("🔥 Мой огонёк", callback_data="my_flames")],
        [InlineKeyboardButton("➕ Добавить друга", callback_data="add_friend"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🔥 *FlameBot* — держи огонёк живым!\n\n"
        f"Привет, *{user.first_name}*!\n\n"
        f"Как это работает:\n"
        f"• Добавь друга по его @username\n"
        f"• Каждый день отправляйте друг другу сообщение через бота\n"
        f"• Огонёк растёт, пока вы оба пишете каждый день\n"
        f"• Пропустил день — огонёк гаснет! ❄️\n\n"
        f"Используй `/help` для списка команд.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Команды FlameBot*\n\n"
        "/start — главное меню\n"
        "/add @username — добавить друга\n"
        "/friends — список друзей и огоньки\n"
        "/msg @username текст — отправить сообщение другу\n"
        "/streak @username — посмотреть огонёк с другом\n"
        "/stats — твоя статистика\n"
        "/me — твой профиль\n"
        "/help — эта справка\n\n"
        "💡 *Совет:* просто напиши `@username текст` чтобы быстро отправить сообщение!",
        parse_mode="Markdown"
    )

async def add_friend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_user(user.id, user.username or "", user.first_name or "")

    # Extract username from args or message text
    target_username = None
    if context.args:
        target_username = context.args[0].lstrip("@")
    
    if not target_username:
        await update.message.reply_text(
            "Укажи @username друга:\n`/add @username`",
            parse_mode="Markdown"
        )
        return

    if target_username.lower() == (user.username or "").lower():
        await update.message.reply_text("🤦 Нельзя добавить самого себя в друзья!")
        return

    friend = db.get_user_by_username(target_username)
    if not friend:
        await update.message.reply_text(
            f"❌ Пользователь @{target_username} не найден.\n"
            f"Попроси его написать боту `/start`!"
        )
        return

    result = db.send_friend_request(user.id, friend['user_id'])

    if result == "already_friends":
        await update.message.reply_text(f"✅ Вы уже друзья с @{target_username}!")
    elif result == "request_exists":
        await update.message.reply_text(f"⏳ Запрос уже отправлен @{target_username}!")
    elif result == "incoming_exists":
        # Auto-accept if they already sent us a request
        db.accept_friend_request(friend['user_id'], user.id)
        flame = db.get_flame(user.id, friend['user_id'])
        await update.message.reply_text(
            f"🎉 @{target_username} уже отправил тебе запрос — вы теперь друзья!\n"
            f"🔥 Начните серию прямо сейчас!"
        )
        await context.bot.send_message(
            chat_id=friend['user_id'],
            text=f"🎉 @{user.username} принял твой запрос в друзья!\n🔥 Начните серию прямо сейчас!"
        )
    elif result == "success":
        await update.message.reply_text(
            f"📨 Запрос отправлен @{target_username}!\nЖди подтверждения."
        )
        keyboard = [[
            InlineKeyboardButton("✅ Принять", callback_data=f"accept_{user.id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_{user.id}")
        ]]
        await context.bot.send_message(
            chat_id=friend['user_id'],
            text=f"👋 *{user.first_name}* (@{user.username}) хочет дружить с тобой в FlameBot!\n"
                 f"Принять запрос?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def friends_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_user(user.id, user.username or "", user.first_name or "")

    friends = db.get_friends(user.id)
    pending = db.get_pending_requests(user.id)

    text = "👫 *Твои друзья:*\n\n"

    if not friends and not pending:
        text += "Пока нет друзей. Добавь первого! `/add @username`"
    else:
        if friends:
            today = date.today()
            for f in friends:
                flame = db.get_flame(user.id, f['user_id'])
                streak = flame['streak'] if flame else 0
                emoji = get_flame_emoji(streak)

                # Check if both messaged today
                my_today = db.checked_in_today(user.id, f['user_id'])
                their_today = db.checked_in_today(f['user_id'], user.id)

                status = ""
                if my_today and their_today:
                    status = " ✅"
                elif my_today:
                    status = " ⏳ждём их"
                elif their_today:
                    status = " 💬напиши!"
                else:
                    status = " 💤"

                name = f['first_name']
                uname = f"@{f['username']}" if f['username'] else ""
                text += f"{emoji} *{name}* {uname} — {streak} дней{status}\n"

        if pending:
            text += "\n📨 *Входящие запросы:*\n"
            for p in pending:
                keyboard = [[
                    InlineKeyboardButton("✅ Принять", callback_data=f"accept_{p['user_id']}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_{p['user_id']}")
                ]]
                text += f"• *{p['first_name']}* (@{p['username']})\n"

    keyboard = [
        [InlineKeyboardButton("➕ Добавить друга", callback_data="add_friend")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_user(user.id, user.username or "", user.first_name or "")

    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: `/msg @username текст сообщения`",
            parse_mode="Markdown"
        )
        return

    target_username = context.args[0].lstrip("@")
    message_text = " ".join(context.args[1:])

    await _send_flame_message(update, context, user, target_username, message_text)

async def _send_flame_message(update, context, user, target_username, message_text):
    friend = db.get_user_by_username(target_username)
    if not friend:
        await update.message.reply_text(f"❌ Пользователь @{target_username} не найден.")
        return

    if not db.are_friends(user.id, friend['user_id']):
        await update.message.reply_text(
            f"❌ Вы не друзья с @{target_username}.\n"
            f"Сначала добавь его: `/add @{target_username}`",
            parse_mode="Markdown"
        )
        return

    already_sent = db.checked_in_today(user.id, friend['user_id'])

    # Record checkin
    db.record_message(user.id, friend['user_id'])

    # Update flame
    flame_result = db.update_flame(user.id, friend['user_id'])
    flame = db.get_flame(user.id, friend['user_id'])
    streak = flame['streak'] if flame else 0
    emoji = get_flame_emoji(streak)

    # Send to friend
    their_today = db.checked_in_today(friend['user_id'], user.id)
    flame_status = ""
    if their_today:
        flame_status = f"\n\n{emoji} Огонёк обновлён! Серия: *{streak} дней* — {get_streak_title(streak)}"
    else:
        flame_status = f"\n\n⏳ Серия обновится когда @{target_username} тоже напишет сегодня"

    await context.bot.send_message(
        chat_id=friend['user_id'],
        text=f"🔥 *Сообщение от @{user.username}:*\n\n{message_text}",
        parse_mode="Markdown"
    )

    if already_sent:
        confirm = f"✅ Сообщение отправлено @{target_username}!\n_(Ты уже писал сегодня)_"
    else:
        confirm = f"✅ Сообщение отправлено @{target_username}!{flame_status}"

    await update.message.reply_text(confirm, parse_mode="Markdown")

    # Notify friend about flame update if both checked in
    if their_today and not already_sent:
        await context.bot.send_message(
            chat_id=friend['user_id'],
            text=f"{emoji} *Огонёк обновлён!*\nСерия с @{user.username}: *{streak} дней*\n_{get_streak_title(streak)}_",
            parse_mode="Markdown"
        )

async def show_streak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_user(user.id, user.username or "", user.first_name or "")

    if not context.args:
        await update.message.reply_text(
            "Использование: `/streak @username`",
            parse_mode="Markdown"
        )
        return

    target_username = context.args[0].lstrip("@")
    friend = db.get_user_by_username(target_username)

    if not friend:
        await update.message.reply_text(f"❌ Пользователь @{target_username} не найден.")
        return

    if not db.are_friends(user.id, friend['user_id']):
        await update.message.reply_text(f"❌ Вы не друзья с @{target_username}.")
        return

    flame = db.get_flame(user.id, friend['user_id'])
    streak = flame['streak'] if flame else 0
    best = flame['best_streak'] if flame else 0
    emoji = get_flame_emoji(streak)

    my_today = db.checked_in_today(user.id, friend['user_id'])
    their_today = db.checked_in_today(friend['user_id'], user.id)

    status_text = ""
    if my_today and their_today:
        status_text = "✅ Оба написали сегодня — огонёк в безопасности!"
    elif my_today:
        status_text = "⏳ Ты написал, ждём @" + target_username
    elif their_today:
        status_text = f"💬 @{target_username} уже написал — твоя очередь!"
    else:
        status_text = "💤 Никто ещё не написал сегодня"

    await update.message.reply_text(
        f"{emoji} *Огонёк с @{target_username}*\n\n"
        f"🔥 Серия: *{streak} дней*\n"
        f"🏆 Рекорд: *{best} дней*\n"
        f"📅 Статус: {status_text}",
        parse_mode="Markdown"
    )

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_user(user.id, user.username or "", user.first_name or "")

    friends = db.get_friends(user.id)
    stats = db.get_user_stats(user.id)

    text = f"📊 *Статистика @{user.username}*\n\n"
    text += f"👫 Друзей: {len(friends)}\n"
    text += f"💬 Всего сообщений: {stats['total_messages']}\n"
    text += f"📅 В боте с: {stats['registered_at'][:10]}\n\n"

    if friends:
        text += "🔥 *Активные серии:*\n"
        for f in friends:
            flame = db.get_flame(user.id, f['user_id'])
            streak = flame['streak'] if flame else 0
            best = flame['best_streak'] if flame else 0
            emoji = get_flame_emoji(streak)
            text += f"{emoji} @{f['username']}: {streak} дней (рекорд: {best})\n"

    if update.callback_query:
        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.register_user(user.id, user.username or "", user.first_name or "")

    best_flame = db.get_best_flame(user.id)

    text = f"👤 *Твой профиль*\n\n"
    text += f"Имя: *{user.first_name}*\n"
    text += f"Username: @{user.username}\n"
    text += f"ID: `{user.id}`\n\n"

    if best_flame:
        streak = best_flame['streak']
        emoji = get_flame_emoji(streak)
        text += f"🏆 Лучший огонёк: {emoji} {streak} дней с @{best_flame['username']}\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text — if starts with @username, treat as message to friend"""
    user = update.effective_user
    text = update.message.text.strip()

    if text.startswith("@"):
        parts = text.split(" ", 1)
        if len(parts) >= 2:
            target_username = parts[0].lstrip("@")
            message_text = parts[1]
            db.register_user(user.id, user.username or "", user.first_name or "")
            await _send_flame_message(update, context, user, target_username, message_text)
            return

    # Otherwise show hint
    friends = db.get_friends(user.id)
    if friends:
        keyboard = []
        for f in friends:
            flame = db.get_flame(user.id, f['user_id'])
            streak = flame['streak'] if flame else 0
            emoji = get_flame_emoji(streak)
            keyboard.append([InlineKeyboardButton(
                f"{emoji} @{f['username']} ({streak} дней)",
                callback_data=f"write_{f['username']}"
            )])
        keyboard.append([InlineKeyboardButton("🏠 Меню", callback_data="main_menu")])

        await update.message.reply_text(
            "💬 Кому отправить сообщение?\n_(или напиши `@username текст`)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "Используй /help для списка команд.\n"
            "Или добавь друга: `/add @username`",
            parse_mode="Markdown"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("👫 Мои друзья", callback_data="friends_list"),
             InlineKeyboardButton("🔥 Мой огонёк", callback_data="my_flames")],
            [InlineKeyboardButton("➕ Добавить друга", callback_data="add_friend"),
             InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        ]
        await query.edit_message_text(
            f"🔥 *FlameBot* — держи огонёк живым!\n\nВыбери действие:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "friends_list":
        await friends_list(update, context)

    elif data == "my_flames":
        await my_stats(update, context)

    elif data == "stats":
        await my_stats(update, context)

    elif data == "add_friend":
        await query.edit_message_text(
            "➕ *Добавить друга*\n\nОтправь команду:\n`/add @username`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Назад", callback_data="main_menu")
            ]])
        )

    elif data.startswith("accept_"):
        requester_id = int(data.split("_")[1])
        db.accept_friend_request(requester_id, user.id)
        flame = db.get_flame(user.id, requester_id)
        requester = db.get_user_by_id(requester_id)

        await query.edit_message_text(
            f"✅ Вы теперь друзья с *{requester['first_name']}*!\n🔥 Начните серию прямо сейчас!",
            parse_mode="Markdown"
        )
        await context.bot.send_message(
            chat_id=requester_id,
            text=f"🎉 *{user.first_name}* принял твой запрос!\n🔥 Напиши ему первым!",
            parse_mode="Markdown"
        )

    elif data.startswith("decline_"):
        requester_id = int(data.split("_")[1])
        db.decline_friend_request(requester_id, user.id)
        requester = db.get_user_by_id(requester_id)
        await query.edit_message_text(
            f"❌ Запрос от *{requester['first_name']}* отклонён.",
            parse_mode="Markdown"
        )

    elif data.startswith("write_"):
        target_username = data.split("_", 1)[1]
        context.user_data['writing_to'] = target_username
        await query.edit_message_text(
            f"✍️ Пишешь *@{target_username}*\n\nОтправь следующим сообщением текст, или используй:\n`/msg @{target_username} текст`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Отмена", callback_data="main_menu")
            ]])
        )

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send daily reminders to users who haven't sent a message today"""
    users = db.get_all_users()
    for user in users:
        friends = db.get_friends(user['user_id'])
        reminders = []
        for f in friends:
            flame = db.get_flame(user['user_id'], f['user_id'])
            if flame and flame['streak'] > 0:
                if not db.checked_in_today(user['user_id'], f['user_id']):
                    emoji = get_flame_emoji(flame['streak'])
                    reminders.append(f"{emoji} @{f['username']} — {flame['streak']} дней под угрозой!")

        if reminders:
            try:
                text = "⚠️ *Не забудь написать сегодня!*\n\n" + "\n".join(reminders)
                await context.bot.send_message(
                    chat_id=user['user_id'],
                    text=text,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to send reminder to {user['user_id']}: {e}")

def main():
    import os
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("❌ Укажи BOT_TOKEN в переменной окружения!")
        print("Например: BOT_TOKEN=your_token python bot.py")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_friend))
    app.add_handler(CommandHandler("friends", friends_list))
    app.add_handler(CommandHandler("msg", send_message))
    app.add_handler(CommandHandler("streak", show_streak))
    app.add_handler(CommandHandler("stats", my_stats))
    app.add_handler(CommandHandler("me", my_profile))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Daily reminder at 20:00
    job_queue = app.job_queue
    job_queue.run_daily(
        daily_reminder,
        time=datetime.strptime("20:00", "%H:%M").time()
    )

    print("🔥 FlameBot запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
