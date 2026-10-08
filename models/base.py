import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimeStampedModel(Base):
    """
    Base Model
    """
    __abstract__ = True

    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        server_default=func.now(), 
        comment="UTC timestamp when record was created"
    )
    
    

    # @classmethod
    # def create_with_id(cls, **kwargs):
    #     instance = cls(**kwargs)
    #     if "id" not in kwargs:
    #         instance.id = uuid.uuid4()
    #     return instance
