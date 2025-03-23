from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
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


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    username = Column(String)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    text = Column(String)  # Первоначальный текст сообщения
    created_at = Column(DateTime, default=datetime)
    is_deleted = Column(Boolean, default=False)  # Флаг удалённого сообщения
    is_edited = Column(
        Boolean, default=False
    )  # Флаг отредактированного сообщения

    user = relationship("User", back_populates="messages")
    versions = relationship("MessageVersion", back_populates="original_message")


User.messages = relationship(
    "Message", order_by=Message.id, back_populates="user"
)


class MessageVersion(Base):
    __tablename__ = "message_versions"
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id"))
    text = Column(String)  # Текст новой версии
    edited_at = Column(DateTime, default=datetime)

    original_message = relationship("Message", back_populates="versions")


Base.metadata.create_all(engine)


def get_or_create_user(session, user_id, username):
    user = session.query(User).filter_by(user_id=user_id).first()
    if not user:
        user = User(user_id=user_id, username=username)
        session.add(user)
        session.commit()
    return user


def save_message(session, chat_id, user_id, text):
    get_or_create_user(
        session, user_id, None
    )  # Имя пользователя можно обновить позже
    message = Message(chat_id=chat_id, user_id=user_id, text=text)
    session.add(message)
    session.commit()


def update_message(session, chat_id, user_id, new_text, edited_at):
    message = (
        session.query(Message)
        .filter_by(chat_id=chat_id, user_id=user_id)
        .first()
    )
    if message:
        message.is_edited = True  # Отмечаем сообщение как отредактированное
        version = MessageVersion(
            message_id=message.id, text=new_text, edited_at=edited_at
        )
        session.add(version)
        session.commit()


def mark_message_as_deleted(session, chat_id, user_id):
    message = (
        session.query(Message)
        .filter_by(chat_id=chat_id, user_id=user_id)
        .first()
    )
    if message:
        message.is_deleted = True
        session.commit()
