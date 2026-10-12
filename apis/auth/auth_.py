from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import select , insert , update , delete
from sqlalchemy.exc import IntegrityError
from models.sessions import get_db
from models.account import Account
from schemas.auth_schema import AccountCreate, AccountSignin
import uuid
import os
import secrets
import bcrypt
from dotenv import load_dotenv
from datetime import datetime , timezone, timedelta
from jose import JWTError , jwt

SECRET_KEY = str(os.getenv("SECRET_KEY"))
ALGORITHM = str(os.getenv("ALGORITHM"))
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

auth_router = APIRouter(
    tags=["AUTHETICATION"]
)


"""
    The two functions below are used to create and verify JWT tokens for user authentication.
"""
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)



def get_current_user(
    token: str = Depends(oauth2_scheme),    
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_Id = payload.get("sub")

        if user_Id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired"
        )
    
    stmt = select(Account).where(Account.userID == user_Id)
    user = db.execute(stmt).scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user

# this funciton is to create a rand string id for the user account
def generate_account_id() -> str:
    return str("USER_"+uuid.uuid4().hex[:8])  # Generate a random string of 8 characters


# In-memory store of pending verification codes.
pending_verification_codes: dict[str, str] = {}


def verification_code_generator() -> str:
    """Generate a 6-digit numeric verification code."""
    return f"{secrets.randbelow(1_000_000):06d}"


class PreferLangBody(BaseModel):
    prefer_lang: str


@auth_router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(account: AccountCreate, db: Session = Depends(get_db)):
    if db.execute(
        select(Account).where(Account.email == account.email)
    ).scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account already exists",
        )
    if db.execute(
        select(Account).where(Account.username == account.username)
    ).scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    user_id = generate_account_id()
    hashed_password = bcrypt.hashpw(
        account.password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    try:
        db.execute(
            insert(Account).values(
                {
                    "userID": user_id,
                    "username": account.username,
                    "email": account.email,
                    "password": hashed_password,
                    "phone_number": account.phone_number,
                    "verified_number": False,
                    "prefer_lang": "english",
                }
            )
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if db.execute(
            select(Account).where(Account.email == account.email)
        ).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Account already exists",
            ) from error
        if db.execute(
            select(Account).where(Account.username == account.username)
        ).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            ) from error
        raise

    return {
        "status": "success",
        "message": "Account created successfully",
        "account_id": user_id,
    }


@auth_router.post("/signin", status_code=status.HTTP_200_OK)
def signin(account: AccountSignin, db: Session = Depends(get_db)):
    try:

        if not account.email or not account.password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email and password are required")

        # == For the organization signin
        loginstmt_ = select(Account).where(Account.email == account.email)
        execute = db.execute(loginstmt_)
        result = execute.scalar_one_or_none()


        if result is None:
            return {"error": "User not found", "role": "wazobia_call"}, 404

        verify = bcrypt.checkpw(account.password.encode('utf-8'), result.password.encode('utf-8'))

        if not verify:
            return {"error": "invalid password", "role": "wazobia_call"}, 401

        access_token = create_access_token(data={"sub": str(result.userID)})

        if result.verified_number == False:
            return {
                "status": "successfull",
                "user_id": result.userID,
                "phone_verified": result.verified_number,
                "token": access_token
            }, 200

        return {
            "status": "successfull",
            "user_id": result.userID,
            "prefer_lang": result.prefer_lang,
            "phone_verified": result.verified_number,
            "token": access_token
        }
        


    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@auth_router.get("/me", status_code=status.HTTP_200_OK)
def get_me(auth_tok: Account = Depends(get_current_user)):
    """
    Return the signed-in user's profile (username, phone number, etc).
    """
    return {
        "status": "success",
        "user_id": auth_tok.userID,
        "username": auth_tok.username,
        "email": auth_tok.email,
        "phone_number": auth_tok.phone_number,
        "verified_number": auth_tok.verified_number,
        "prefer_lang": auth_tok.prefer_lang,
    }


@auth_router.post("/prefer_lang", status_code=status.HTTP_200_OK)
def update_prefer_lang(
    body: PreferLangBody,
    auth_tok: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the signed-in user's preferred language (used for call STT).
    """
    language = (body.prefer_lang or "").strip().lower()
    if not language:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prefer_lang is required",
        )

    update_lang = update(Account).where(
        Account.phone_number == auth_tok.phone_number
    ).values(
        prefer_lang = language
    )

    db.execute(update_lang)
    db.commit()

    return {"status": "success", "prefer_lang": auth_tok.prefer_lang}


"""
    This is to delete the user account in total
"""
@auth_router.delete("/delete_account", status_code=status.HTTP_200_OK)
def delete_account(userMail: str , db: Session = Depends(get_db)):
    try:
        
        # Delete the account from the database
        delete_stmt = delete(Account).where(Account.email == userMail)
        db.execute(delete_stmt)
        db.commit()

        return {
            "status": "success",
            "message": "Account deleted successfully"
        }

    except Exception as error:
        return {
            "status":"error",
            "message":str(error)
        }