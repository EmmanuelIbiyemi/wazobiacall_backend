from fastapi import APIRouter
from .auth_ import auth_router
from .verify import verify_router


authentication = APIRouter(
    prefix="/auth",
)

authentication.include_router(auth_router)
authentication.include_router(verify_router)