from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

# SMS sending is temporarily disabled — the code is printed to the server logs
# instead (see verify_number below).
# from apis.termii import send_verification_code
from models.account import Account
from models.sessions import get_db
from .auth_ import (
    get_current_user,
    pending_verification_codes,
    verification_code_generator,
)

verify_router = APIRouter(tags=["Verify"])


class VerifyCodeBody(BaseModel):
    code: str | None = None


@verify_router.post("/verify-number", status_code=status.HTTP_200_OK)
def verify_number(
    body: VerifyCodeBody,
    auth_tok: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a verification code by SMS or validate a submitted code."""
    user_id = auth_tok.userID
    submitted = (body.code or "").strip()

    # No code, or "0", means "send me a (new) code" (used by the resend button).
    if submitted in ("", "0"):
        new_code = verification_code_generator()
        print(f"Verification code for {user_id}: {new_code}")
        # await send_verification_code(auth_tok.phone_number, new_code)
        pending_verification_codes[user_id] = new_code
        return {"status": "success", "message": "Verification code sent by SMS"}

    expected = pending_verification_codes.get(user_id)
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code generated",
        )

    if submitted != expected:
        return {"status": "error", "message": "Invalid verification code"}

    db.execute(
        update(Account)
        .where(Account.userID == user_id)
        .values(verified_number=True)
    )
    db.commit()
    pending_verification_codes.pop(user_id, None)

    return {"status": "success", "message": "Phone number verified successfully"}