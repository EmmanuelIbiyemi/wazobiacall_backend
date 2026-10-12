from apis.sms_sender.termii import send_invitation


async def verif_func(phone_number: str, caller_name: str) -> dict[str, str]:
    """Send an SMS invitation to a phone number not registered in the app."""
    return await send_invitation(phone_number, caller_name)
