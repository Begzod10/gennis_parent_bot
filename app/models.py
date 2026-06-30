from datetime import datetime, timezone
from sqlalchemy import Integer, String, BigInteger, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    lang: Mapped[str] = mapped_column(String(5), default="uz")


class ParentSubscription(Base):
    __tablename__ = "parent_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    parent_name: Mapped[str] = mapped_column(String(100), nullable=True)
    student_platform_id: Mapped[int] = mapped_column(Integer)
    student_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
