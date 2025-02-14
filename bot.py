import logging

from config import Config
from database import (
    Message,
    MessageVersion,
    Session,
    mark_message_as_deleted,
    save_message,
    update_message,
)
from telegram import ChatMemberUpdated, Update
from telegram.ext import (
    Application,
    CallbackContext,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def handle_new_message(update: Update, context: CallbackContext) -> None:
    if update.effective_user.is_bot:
        logger.info(f"Ignoring message from bot: {update.effective_user.username}")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username
    text = update.message.text

    session = Session()
    try:
        save_message(session, chat_id, user_id, text)
        logger.info(f"Saved message from {username}: {text}")
    except Exception as e:
        logger.error(f"Error saving message: {e}")
    finally:
        session.close()


async def handle_edited_message(update: Update, context: CallbackContext) -> None:
    if update.effective_user.is_bot:
        logger.info(
            f"Ignoring edited message from bot: {update.effective_user.username}"
        )
        return

    chat_id = update.edited_message.chat_id
    user_id = update.edited_message.from_user.id
    new_text = update.edited_message.text
    edited_at = update.edited_message.edit_date

    session = Session()
    try:
        update_message(session, chat_id, user_id, new_text, edited_at)
        logger.info(f"Message edited by {update.effective_user.username}: {new_text}")
    except Exception as e:
        logger.error(f"Error handling edited message: {e}")
    finally:
        session.close()


async def handle_deleted_message(update: Update, context: CallbackContext) -> None:
    if update.effective_user.is_bot:
        logger.info(
            f"Ignoring deleted message from bot: {update.effective_user.username}"
        )
        return

    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    session = Session()
    try:
        mark_message_as_deleted(session, chat_id, user_id)
        logger.info(f"Message marked as deleted by {update.effective_user.username}")
    except Exception as e:
        logger.error(f"Error handling deleted message: {e}")
    finally:
        session.close()


async def track_chat_members(update: Update, context: CallbackContext) -> None:
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    member = update.chat_member.new_chat_member.user

    if member.is_bot:
        logger.info(f"Ignoring bot member change: {member.username}")
        return

    chat_title = update.chat_member.chat.title or "Private Chat"

    if not was_member and is_member:
        await notify_admins(
            context,
            update.effective_chat.id,
            f"Пользователь {member.name} был добавлен в чат '{chat_title}'.",
        )
    elif was_member and not is_member:
        await notify_admins(
            context,
            update.effective_chat.id,
            f"Пользователь {member.name} покинул чат '{chat_title}'.",
        )


async def notify_admins(context: CallbackContext, chat_id: int, message: str) -> None:
    try:
        # Получаем список администраторов чата
        admins = await context.bot.get_chat_administrators(chat_id)

        for admin in admins:
            if not admin.user.is_bot:  # Исключаем ботов
                try:
                    await context.bot.send_message(chat_id=admin.user.id, text=message)
                    logger.info(f"Notified admin {admin.user.name}: {message}")
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin.user.name}: {e}")
    except Exception as e:
        logger.error(f"Failed to fetch administrators: {e}")


def extract_status_change(chat_member_update: ChatMemberUpdated):
    status_change = chat_member_update.difference().get("status")
    old_status, new_status = status_change if status_change else (None, None)

    was_member = old_status in [
        "member",
        "restricted",
        "creator",
        "administrator",
    ]
    is_member = new_status in [
        "member",
        "restricted",
        "creator",
        "administrator",
    ]

    return was_member, is_member


async def search_hashtag(update: Update, context: CallbackContext) -> None:
    # Проверяем, является ли пользователь администратором
    if not await is_user_admin(update, context):
        await update.message.reply_text(
            "Эта команда доступна только администраторам чата."
        )
        return

    # Получаем хештег из аргументов команды
    hashtag = context.args[0] if context.args else None
    if not hashtag or not hashtag.startswith("#"):
        await update.message.reply_text(
            "Укажите хештег для поиска (например, /search_hashtag #example)."
        )
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Ищем сообщения по хештегу
    results = await find_messages_by_hashtag(chat_id, hashtag)

    if results:
        # Отправляем результаты поиска администратору в личные сообщения
        message = "Результаты поиска по хештегу:\n\n"
        for msg in results:
            message += f"Текст: {msg['text']}\nАвтор: {msg['author']}\n\n"

        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            logger.info(
                f"Searched hashtag #{hashtag} by admin {update.effective_user.name}"
            )
        except Exception as e:
            logger.error(f"Failed to send search results to admin: {e}")
    else:
        await context.bot.send_message(
            chat_id=user_id, text="Сообщения с указанным хештегом не найдены."
        )


async def is_user_admin(update: Update, context: CallbackContext) -> bool:
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["creator", "administrator"]
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False


async def find_messages_by_hashtag(chat_id: int, hashtag: str) -> list:
    session = Session()
    try:
        # Ищем первоначальные сообщения
        messages = (
            session.query(Message)
            .filter(Message.chat_id == chat_id, Message.text.like(f"%{hashtag}%"))
            .all()
        )

        # Ищем отредактированные версии сообщений
        versions = (
            session.query(MessageVersion)
            .join(Message)
            .filter(
                Message.chat_id == chat_id, MessageVersion.text.like(f"%{hashtag}%")
            )
            .all()
        )

        results = []
        for msg in messages:
            results.append(
                {"text": msg.text, "author": msg.user.username or msg.user.user_id}
            )

        for version in versions:
            results.append(
                {
                    "text": version.text,
                    "author": version.original_message.user.username
                    or version.original_message.user.user_id,
                }
            )

        return results
    except Exception as e:
        logger.error(f"Error searching messages by hashtag: {e}")
        return []
    finally:
        session.close()


def main() -> None:
    application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()

    # Обработчик новых сообщений
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_message)
    )

    # Обработчик отредактированных сообщений
    application.add_handler(
        MessageHandler(filters.Update.EDITED_MESSAGE, handle_edited_message)
    )

    # Обработчик удалённых сообщений
    application.add_handler(
        MessageHandler(
            filters.COMMAND & filters.Regex(r"^/delete"), handle_deleted_message
        )
    )

    # Обработчик изменений участников чата
    application.add_handler(
        ChatMemberHandler(track_chat_members, ChatMemberHandler.CHAT_MEMBER)
    )

    # Обработчик команды поиска по хештегу
    application.add_handler(CommandHandler("search_hashtag", search_hashtag))

    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
