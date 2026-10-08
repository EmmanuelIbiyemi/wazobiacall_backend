from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import select , insert , update , delete
from models.sessions import get_db
from models.account import Account
from schemas.auth_schema import AccountCreate, AccountSignin
import uuid
import os
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


@auth_router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(account: AccountCreate, db: Session = Depends(get_db)):
    try:

        # Check if the email already exists
        existing_account = db.execute(select(Account).where(Account.email == account.email)).scalar_one_or_none()
        if existing_account:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

        hashed_password = bcrypt.hashpw(account.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


        # Create a new account
        new_account = insert(Account).values(
            {
                "userID": str(generate_account_id()),
                "username": account.username,
                "email": account.email,
                "password": hashed_password,
                "phone_number": account.phone_number,
                "verified_number": False,
                "prefer_lang": "englih"
            }
        )
        db.execute(new_account)
        db.commit()

        return {
            "status": "success",
            "message": "Account created successfully",
            "account_id": str(generate_account_id())
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
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


        if result != None:
            verify = bcrypt.checkpw(account.password.encode('utf-8'), result.password.encode('utf-8'))


            if result and verify:
                access_token = create_access_token(data={"sub": str(result.userID)})

                if result.verified_number == False:
                    return {
                        "status":"successfull",
                        "user_id": result.userID,
                        "phone_verified":result.verified_number,
                        "token":access_token
                    }, 200
                elif result.verified_number == True:
                    
                    return {
                        "status":"successfull",
                        "user_id": result.userID,
                        "prefer_lang":result.prefer_lang,
                        "phone_verified":result.verified_number,
                        "token": access_token
                    }
        elif result and not verify :
                return {"error": "Invalid password", "role": "wazobia_call"}, 401
            
        elif not result:
                return {"error": "User not found", "role": "wazobia_call"}, 404
        


    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


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