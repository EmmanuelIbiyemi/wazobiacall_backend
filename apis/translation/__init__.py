from fastapi import APIRouter 

from .makecall import calling

call_translate = APIRouter(
    prefix="/wazobia_call",
    tags=["WAZOBIA"]
)

call_translate.include_router(calling)