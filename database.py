from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

path = Path(__file__).parent.joinpath("db_url.txt")
with path.open() as f:
    DATABASE_URL = f.read().strip()

Base = declarative_base()
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


@contextmanager
def session_scope():
    """Контекстный менеджер для работы с сессией базы данных."""
    session = Session()
    try:
        yield session
        session.commit()  # Коммит изменений после успешного выполнения
    except Exception as e:
        session.rollback()  # Откат изменений в случае ошибки
        raise e  # Повторно выбрасываем исключение
    finally:
        session.close()  # Закрываем сессию


class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, unique=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)

    messages = relationship("Message", back_populates="user")


class Message(Base):
    __tablename__ = "messages"
    id = Column(BigInteger, primary_key=True, autoincrement=False)
    chat_id = Column(BigInteger)
    user_id = Column(BigInteger, ForeignKey("users.user_id"))
    text = Column(String)  # Первоначальный текст сообщения
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    is_edited = Column(Boolean, default=False)

    user = relationship("User", back_populates="messages")
    versions = relationship("MessageVersion", back_populates="original_message")


class MessageVersion(Base):
    __tablename__ = "message_versions"
    id = Column(BigInteger, primary_key=True)
    message_id = Column(BigInteger, ForeignKey("messages.id"))
    text = Column(String)  # Текст новой версии
    edited_at = Column(DateTime, default=datetime.utcnow)

    original_message = relationship("Message", back_populates="versions")


Base.metadata.create_all(engine)


def get_or_create_user(session, user):
    user_id = user.id
    username = user.username
    full_name = user.full_name
    first_name = user.first_name
    last_name = user.last_name

    existing_user = session.query(User).filter_by(user_id=user_id).first()
    if not existing_user:
        # Создаём нового пользователя
        new_user = User(
            user_id=user_id,
            username=username,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(new_user)
    else:
        # Обновляем данные пользователя, если они изменились
        if username and existing_user.username != username:
            existing_user.username = username
        # if first_name and user.first_name != first_name:
        #     user.first_name = first_name
        # if last_name and user.last_name != last_name:
        #     user.last_name = last_name
    session.commit()
    return existing_user or new_user


def save_message(session, chat_id, user, text, message_id=None):
    try:
        get_or_create_user(session, user)
        message = Message(
            id=message_id, chat_id=chat_id, user_id=user.id, text=text
        )
        session.add(message)
    except Exception as e:
        session.rollback()
        raise e


def update_message(session, chat_id, user_id, message_id, new_text, edited_at):
    try:
        message = (
            session.query(Message)
            .filter_by(chat_id=chat_id, user_id=user_id, id=message_id)
            .first()
        )
        if message:
            message.is_edited = True
            version = MessageVersion(
                message_id=message.id, text=new_text, edited_at=edited_at
            )
            session.add(version)
    except Exception as e:
        session.rollback()
        raise e


def mark_message_as_deleted(session, chat_id, user_id):
    try:
        message = (
            session.query(Message)
            .filter_by(chat_id=chat_id, user_id=user_id)
            .first()
        )
        if message:
            message.is_deleted = True
    except Exception as e:
        session.rollback()
        raise e
