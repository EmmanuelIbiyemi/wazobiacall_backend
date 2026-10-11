from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from dotenv import load_dotenv

# The auth router
from apis.auth import authentication

# This is for the call
# from apis.translation import call_translate

# This is for the voip call
from apis.call import calls

load_dotenv()


call = FastAPI(
    title="Call API",
    description="API for Call Translate application",
)

hosted_domain = os.getenv("HOST_FRONTEND_LINK")

call.include_router(authentication)
call.include_router(calls)
# call.include_router(call_translate)

origins = [
     "*",
    "http://localhost:3000",
    "http://localhost:8000",
    "https://skied-custody-shrouded.ngrok-free.dev",
    hosted_domain
]

call.add_middleware(
    CORSMiddleware,
    # All this comment cause of antigravity
    # pyrefly: ignore [bad-argument-type]
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@call.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Turn FastAPI's default 422 body into the app's {status, message} shape.
    """
    details = []
    for error in exc.errors():
        loc = [str(part) for part in error.get("loc", ()) if part != "body"]
        message = str(error.get("msg", "Invalid value"))
        # Pydantic prefixes custom ValueError messages with "Value error, "
        if message.startswith("Value error, "):
            message = message[len("Value error, "):]
        details.append({
            "field": loc[-1] if loc else None,
            "message": message,
        })

    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "message": "; ".join(detail["message"] for detail in details) or "Validation failed",
            "errors": details,
        },
    )


@call.get("/")
def read_root():
    return {"Call": "Welcome to Call Translate API for the frontend"}


