import logging
from pathlib import Path

from telegram import ChatMemberUpdated, Update
from telegram.ext import (
    Application,
    CallbackContext,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from database import (
    Message,
    MessageVersion,
    save_message,
    session_scope,
    update_message,
)

path = Path(__file__).parent.joinpath("token.txt")
print(path)
with path.open() as f:
    TELEGRAM_BOT_TOKEN = f.read().strip()


# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def handle_new_message(update: Update, context: CallbackContext) -> None:
    if update.effective_user.is_bot:
        logger.info(
            f"Ignoring message from bot: {update.effective_user.username}"
        )
        return

    if update.message is None or update.message.text is None:
        logger.info("Message does not contain text, skipping...")
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text
    message_id = update.message.message_id

    try:
        with session_scope() as session:
            save_message(session, chat_id, user, text, message_id)
            logger.info(f"Saved message from {user.username}: {text}")
    except Exception as e:
        logger.error(f"Error saving message from {user.username}: {e}")


async def handle_edited_message(
    update: Update, context: CallbackContext
) -> None:
    if update.effective_user.is_bot:
        logger.info(
            f"Ignoring edited message from bot: {update.effective_user.username}"
        )
        return

    if update.edited_message is None:
        logger.info("Edited message is None, skipping...")
        return

    chat_id = update.edited_message.chat_id
    user = update.edited_message.from_user
    if user is None:
        logger.info("User information is None, skipping...")
        return
    message_id = update.edited_message.message_id
    new_text = update.edited_message.text
    edited_at = update.edited_message.edit_date

    logger.info(
        f"Handling edited message: chat_id={chat_id}, user_id={user.id}, new_text={new_text}"
    )

    try:
        with session_scope() as session:
            update_message(
                session, chat_id, user.id, message_id, new_text, edited_at
            )
            logger.info(f"Message edited by {user.username}: {new_text}")
    except Exception as e:
        logger.error(f"Error handling edited message: {e}")


async def track_chat_members(update: Update, context: CallbackContext) -> None:
    if not update.chat_member:
        logger.warning("No chat_member information in the update.")
        return

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
        message = f"Пользователь {member.full_name} был добавлен в чат '{chat_title}'."
        logger.info(message)
        try:
            await notify_admins(context, update.effective_chat.id, message)
        except Exception as e:
            logger.error(f"Error notifying admins about new member: {e}")
    elif was_member and not is_member:
        message = f"Пользователь {member.full_name} покинул чат '{chat_title}'."
        logger.info(message)
        try:
            await notify_admins(context, update.effective_chat.id, message)
        except Exception as e:
            logger.error(f"Error notifying admins about member leaving: {e}")


async def notify_admins(
    context: CallbackContext, chat_id: int, message: str
) -> None:
    try:
        # Получаем список администраторов чата
        admins = await context.bot.get_chat_administrators(chat_id)

        if not admins:
            logger.info("No administrators found in the chat.")
            return

        notified_count = 0

        for admin in admins:
            if not admin.user.is_bot:  # Исключаем ботов
                try:
                    await context.bot.send_message(
                        chat_id=admin.user.id, text=message
                    )
                    logger.info(
                        f"Notified admin {admin.user.full_name}: {message}"
                    )
                    notified_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to notify admin {admin.user.full_name}: {e}"
                    )

        logger.info(f"Total notified admins: {notified_count}")

    except Exception as e:
        logger.error(f"Failed to fetch administrators: {e}")


def extract_status_change(
    chat_member_update: ChatMemberUpdated,
) -> tuple[bool, bool]:
    # Извлекаем изменения статуса
    status_change = chat_member_update.difference().get("status", (None, None))

    # Получаем старый и новый статус
    old_status, new_status = status_change

    # Определяем, был ли пользователь участником чата и является ли он участником сейчас
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

    # Логируем изменения статуса
    logger.info(
        f"Status changed from {old_status} to {new_status}. Was member: {was_member}, Is member: {is_member}"
    )

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

    try:
        # Ищем сообщения по хештегу
        results = await find_messages_by_hashtag(chat_id, hashtag)

        if results:
            # Формируем сообщение с результатами поиска
            message_lines = [
                f"Текст: {msg['text']}\nАвтор: {msg['author']}\n"
                for msg in results
            ]
            message = "Результаты поиска по хештегу:\n\n" + "\n\n".join(
                message_lines
            )

            await context.bot.send_message(chat_id=user_id, text=message)
            logger.info(
                f"Searched hashtag #{hashtag} by admin {update.effective_user.name}"
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="Сообщения с указанным хештегом не найдены.",
            )
    except Exception as e:
        logger.error(f"Error while searching for hashtag #{hashtag}: {e}")
        await context.bot.send_message(
            chat_id=user_id, text="Произошла ошибка при поиске сообщений."
        )


async def is_user_admin(update: Update, context: CallbackContext) -> bool:
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        chat_member = await context.bot.get_chat_member(chat_id, user_id)

        # Логируем информацию о статусе
        logger.info(
            f"User {user_id} status in chat {chat_id}: {chat_member.status}"
        )

        return chat_member.status in ["creator", "administrator"]
    except Exception as e:
        logger.error(
            f"Error checking admin status for user {user_id} in chat {chat_id}: {e}"
        )
        return False


async def find_messages_by_hashtag(chat_id: int, hashtag: str) -> list:
    try:
        with session_scope() as session:
            # Ищем первоначальные сообщения
            messages = (
                session.query(Message)
                .filter(
                    Message.chat_id == chat_id,
                    Message.text.like(f"%{hashtag}%"),
                )
                .all()
            )

            # Ищем отредактированные версии сообщений
            versions = (
                session.query(MessageVersion)
                .join(Message)
                .filter(
                    Message.chat_id == chat_id,
                    MessageVersion.text.like(f"%{hashtag}%"),
                )
                .all()
            )

            results = []
            for msg in messages:
                results.append(
                    {
                        "text": msg.text,
                        "author": msg.user.username or msg.user.user_id,
                    }
                )

            for version in versions:
                results.append(
                    {
                        "text": version.text,
                        "author": version.original_message.user.username
                        or version.original_message.user.user_id,
                    }
                )

            logger.info(
                f"Found {len(results)} messages for hashtag {hashtag} in chat {chat_id}."
            )
            return results

    except Exception as e:
        logger.error(
            f"Error searching messages by hashtag '{hashtag}' in chat {chat_id}: {e}"
        )
        return []


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Обработчик отредактированных сообщений
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.UpdateType.EDITED_MESSAGE,
            handle_edited_message,
        )
    )

    # Обработчик новых сообщений
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_message)
    )

    # Обработчик изменений участников чата
    application.add_handler(
        ChatMemberHandler(track_chat_members, ChatMemberHandler.CHAT_MEMBER)
    )

    # Обработчик команды поиска по хештегу
    application.add_handler(
        CommandHandler(
            "search_hashtag",
            search_hashtag,
            filters=filters.ChatType.GROUP | filters.ChatType.SUPERGROUP,
        )
    )

    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
