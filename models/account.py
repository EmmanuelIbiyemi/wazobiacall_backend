from models.base import TimeStampedModel
from sqlalchemy import Column, Integer, String, Boolean, Date , func

class Account(TimeStampedModel):
    """
    Account model
    """

    __tablename__ = "users"

    userID: str = Column(String(225), primary_key=True)
    username: str = Column(String(50), unique=True, nullable=False)
    email: str = Column(String(255), unique=True, nullable=False)
    password: str = Column(String(255), nullable=False)
    phone_number: str = Column(String(20), nullable=False)
    verified_number: bool = Column(Boolean, default=False)
    prefer_lang: str = Column(String(10), nullable=False)
    created_at: Date = Column(Date, nullable=False , server_default=func.now())
