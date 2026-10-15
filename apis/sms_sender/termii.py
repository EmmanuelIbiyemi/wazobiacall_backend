import logging
import os
# import asyncio
import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

log = logging.getLogger(__name__)

SMS_SEND_PATH = "/api/v1/sms/send"

load_dotenv()

def sms_url(base_url: str) -> str:
    """Build the Termii send-SMS URL from a configured base URL.

    Accepts the bare domain (e.g. https://v4.api.termii.com) or the full
    endpoint, and always returns the send endpoint.
    """
    url = base_url.rstrip("/")
    if not url.endswith(SMS_SEND_PATH):
        url += SMS_SEND_PATH
    return url


async def send_sms(phone_number: str, message: str) -> dict[str, str]:
    base_url = os.getenv("TERMII_BASE_URL")
    api_key = os.getenv("TERMII_API_KEY")
    sender_id = os.getenv("TERMII_SENDER_ID")
    print(base_url)
    print(api_key)
    print(sender_id)
    if not base_url or not api_key or not sender_id:
        log.error("Termii SMS is not configured; required environment variables are missing")
        raise HTTPException(status_code=503, detail="SMS is not configured")
    
    
    payload = {
        "api_key":api_key,
        "to": phone_number,
        "from": sender_id,
        "sms": message,
        "type": "plain",
        "channel": "dnd"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                sms_url(base_url),
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            print(response.text)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("Termii failed to send SMS: %s", exc)
        raise HTTPException(status_code=502, detail="Could not send SMS") from exc

    return {"status": "successful", "message": response.text}


async def send_verification_code(phone_number: str, code: str) -> dict[str, str]:
    return await send_sms(
        phone_number,
        f"Your Wazobia Call verification code is {code}.",
    )


async def send_invitation(phone_number: str, caller_name: str) -> dict[str, str]:
    return await send_sms(
        phone_number,
        f"{caller_name} is trying to call you on Wazobia Call. "
        "Install the app and sign up to receive their call.",
    )


# asyncio.run(send_verification_code(phone_number="2347079774479", code="333433"))