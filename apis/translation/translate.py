from fastapi import APIRouter, Depends, HTTPException, status
# Download the helper library from https://www.twilio.com/docs/python/install
import os
from twilio.rest import Client


make_call = APIRouter(
    prefix="/call",
    tags=["Call"],
)




# Find your Account SID at twilio.com/console
# Provision API Keys at twilio.com/console/runtime/api-keys
# and set the environment variables. See http://twil.io/secure
# For local testing, you can use your Account SID and Auth token
api_key = os.environ["TWILIO_API_KEY"]
api_secret = os.environ["TWILIO_API_SECRET"]
account_sid = os.environ["TWILIO_ACCOUNT_SID"]
client = Client(api_key, api_secret, account_sid)

call = client.calls.create(
    url="http://demo.twilio.com/docs/voice.xml",
    to="+18005550100",
    from_="+18005550199",
)

print(call.sid)


@make_call.get("/make-call")
async def make_call():
    try:
        pass

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }