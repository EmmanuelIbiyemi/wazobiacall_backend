from fastapi import APIRouter
from .auth_ import auth_router


authentication = APIRouter(
    prefix="/auth",
)

authentication.include_router(auth_router)