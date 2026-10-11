from fastapi import APIRouter 

from .voipcall import voip_calls
calls =APIRouter(
    prefix="/voip_call"
)

calls.include_router(voip_calls)