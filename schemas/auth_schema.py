from pydantic import BaseModel, EmailStr, Field , field_validator 

class AccountCreate(BaseModel):
    username: str = Field(..., description="User's username")
    phone_number: str = Field(..., description="User's phone number")
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="User's password")

    @field_validator("username")
    def validate_username(cls, username: str) -> str:
        """
        Validate username
        """
        if not username or len(username) < 3:
            raise ValueError("Username must be at least 3 characters long")
        return username

    @field_validator("email")
    def validate_email(cls, email: str) -> str:
        """
        Validate email address
        """
        if not email or "@" not in email or len(email) < 5:
            raise ValueError("Invalid email address")
        return email

    @field_validator("password")
    def validate_password(cls, password: str) -> str:
        """
        Validate password
        """
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return password

    @field_validator("phone_number")
    def validate_phone_number(cls, phone_number: str) -> str:
        """
        Validate phone number
        """
        if not phone_number or len(phone_number) < 10:
            raise ValueError("Invalid phone number")
        return phone_number


class AccountSignin(BaseModel):
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="User's password")

    @field_validator("email")
    def validate_email(cls, email: str) -> str:
        """
        Validate email address
        """
        if not email or "@" not in email or len(email) < 5:
            raise ValueError("Invalid email address")
        return email

    @field_validator("password")
    def validate_password(cls, password: str) -> str:
        """
        Validate password
        """
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return password