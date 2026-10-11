import os
import json
import base64
from fastapi import APIRouter, WebSocket
from fastapi.responses import Response
from twilio.rest import Client

calling = APIRouter(
    tags=["MAKE CALL"]
)

# 1. Twilio Credentials (Replace with your actual keys or set env variables)
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "your_account_sid")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "your_auth_token")
TWILIO_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "+12345678901")  # Your purchased Twilio number

# Your public server URL (Must be HTTPS/WSS, use ngrok for local testing)
PUBLIC_DOMAIN = "mubexdot.dev" 

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


# ==========================================
# SECTION 1: THE OUTBOUND CALL TRIGGER
# ==========================================
@calling.post("/make-call")
def make_call(to_number: str):
    """
    Call this endpoint to trigger the outbound phone call.
    It tells Twilio to call a customer and look at /twiml for instructions.
    """
    try:
        call = client.calls.create(
            to=to_number,
            from_=TWILIO_NUMBER,
            url=f"https://{PUBLIC_DOMAIN}/twiml"
        )
        return {"status": "success", "call_sid": call.sid}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================
# SECTION 2: THE TWIML ROUTE (<Start><Stream>)
# ==========================================
@calling.post("/twiml")
def get_twiml():
    """
    When the user answers, Twilio reads this XML.
    It initiates the <Stream> over a WebSocket connection.
    """
    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>Connecting your live stream audio now.</Say>
        <Start>
            <Stream url="wss://{PUBLIC_DOMAIN}/media-stream" />
        </Start>
        <Pause length="40"/>
    </Response>
    """
    return Response(content=twiml_response, media_type="calllication/xml")


# ==========================================
# SECTION 3: THE LIVE WEBSOCKET AUDIO STREAM
# ==========================================
@calling.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """
    This is where the raw audio streams every couple of milliseconds.
    """
    await websocket.accept()
    print("\n--- WebSocket Connected to Twilio Live Stream ---")

    try:
        while True:
            # Twilio sends JSON data packets over the socket constantly
            message = await websocket.receive_text()
            data = json.loads(message)

            if data['event'] == 'start':
                print(f"Stream Started! Stream SID: {data['start']['streamSid']}")

            elif data['event'] == 'media':
                # This block runs every few milliseconds!
                media = data['media']
                payload = media['payload'] # Raw audio in Base64 encoding
                
                # Decode the base64 payload into raw binary PCM/mulaw bytes
                raw_audio_bytes = base64.b64decode(payload)
                
                # Visual output to prove data is moving millisecond by millisecond
                print(f" Received raw audio chunk | Timestamp: {media['timestamp']}ms | Size: {len(raw_audio_bytes)} bytes")

            elif data['event'] == 'stop':
                print("Stream Stopped by Twilio.")
                break

    except Exception as e:
        print(f"Connection closed or error encountered: {e}")
    finally:
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    # Run the server locally on port 8000
    uvicorn.run(call, host="0.0.0.0", port=8000)
