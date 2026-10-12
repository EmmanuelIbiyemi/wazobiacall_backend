import asyncio
import logging
import os
import time
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException
from livekit import api as lk
from schemas.voipschema import CallBody, AcceptBody
from apis.auth.auth_ import get_current_user
from models.account import Account
from models.sessions import get_db
from sqlalchemy import select
from sqlalchemy.orm import Session

from .providers import STTResult, STT_REGISTRY, preload
from .translation import translate, is_configured
from .voidBot import run_bot
from .termii import send_invitation

LK_KEY = os.environ["LIVEKIT_API_KEY"]
LK_SECRET = os.environ["LIVEKIT_API_SECRET"]
calls: dict[str, dict] = {}
transcription_tasks: dict[str, asyncio.Task[None]] = {}
# Keeps background model-warmup tasks referenced until they finish.
_preload_tasks: set[asyncio.Task[None]] = set()
log = logging.getLogger(__name__)

# Room capacity: the two call parties plus the hidden transcription bot
# (see voidBot.run_bot), so only the two callers can ever be in a room.
MAX_ROOM_PARTICIPANTS = 3
# A just-started call has nobody in the room yet; give it a moment before
# treating an empty room as a dead call.
ROOM_CHECK_GRACE_SECONDS = 10
# Identity prefix of the hidden transcription bot (not a real caller).
BOT_IDENTITY_PREFIX = "transcriber-"

LANGUAGE_CODES = {
    "english": "en",
    "yoruba": "yo",
    "igbo": "ig",
    "hausa": "ha",
    "nigerian pidgin": "pcm",
    "pidgin": "pcm"
}

# STT/TTS only have real models for these; anything else falls back to English.
STT_LANGUAGE_CODES = {"yo", "ig", "ha", "en", "pcm"}


def stt_language(preferred_language: str | None) -> str:
    language = (preferred_language or "en").strip().lower()
    if language in LANGUAGE_CODES:
        return LANGUAGE_CODES[language]
    if language in STT_LANGUAGE_CODES:
        return language
    log.warning("Unsupported STT language %r; defaulting to English", preferred_language)
    return "en"


def phone_variants(number: str) -> set[str]:
    normalized = normalize_phone(number)
    digits = normalized.lstrip("+")
    variants = {number, normalized, digits}
    if digits.startswith("234"):
        variants.add("0" + digits[3:])
    return {variant for variant in variants if variant}


def start_transcription(room: str, caller: str, callee: str, langs: dict[str, str]) -> None:
    # Each party hears the other party's language.
    targets = {
        caller: langs.get(callee, "en"),
        callee: langs.get(caller, "en"),
    }

    async def publish_transcript(speaker: str, result: STTResult, language: str) -> None:
        text = result.text.strip()
        if not text:
            return
        speaker_number = normalize_phone(speaker)
        is_caller = speaker_number == caller
        is_callee = speaker_number == callee
        listener = callee if is_caller else caller
        speaker_label = (
            "Caller 1" if is_caller else "Caller 2" if is_callee else "Unknown caller"
        )
        listener_label = (
            "Caller 2" if is_caller else "Caller 1" if is_callee else "other party"
        )
        target_language = targets.get(speaker_number, language)

        # Translate what was said into the language the other party speaks.
        translated = await translate(text, language, target_language)

        print(
            f"[{speaker_label} | {speaker_number}] spoke ({language}): {text}"
            f"{'' if result.is_final else ' (interim)'}",
            flush=True,
        )
        # Always show what the other party should hear, tagged with their code,
        # so it is obvious when translation is not configured yet.
        print(
            f"  -> for [{listener_label} | {listener}] in ({target_language}): {translated}",
            flush=True,
        )

        message = {
            "event": "transcription",
            "room": room,
            "caller": caller,
            "callee": callee,
            "speaker": speaker_number,
            "speaker_label": speaker_label,
            "listener": listener,
            "text": text,
            "translated": translated,
            "final": result.is_final,
            "language": language,
            "target_language": target_language,
        }
        # Send only to the listener (the other party). Each party therefore
        # receives only the *other* person's speech, already translated into
        # their own preferred language — never their own words echoed back.
        print(
            f"[STT websocket] sending to {listener}: "
            f"{len(hub.clients.get(listener, ()))} connected frontend socket(s)",
            flush=True,
        )
        await hub.send(listener, message)

        # Also push a "translation" event so the listener's app speaks the
        # translated text aloud (TTS). Only final utterances are spoken, so
        # interim chunks never trigger a voice.
        if result.is_final:
            await hub.send(
                listener,
                {
                    "event": "translation",
                    "room": room,
                    "translated": translated,
                    "lang": target_language,
                },
            )

    task = asyncio.create_task(
        run_bot(room, langs, on_transcript=publish_transcript)
    )
    transcription_tasks[room] = task

    def on_done(completed: asyncio.Task[None]) -> None:
        if transcription_tasks.get(room) is completed:
            transcription_tasks.pop(room, None)
        if completed.cancelled():
            return
        error = completed.exception()
        if error:
            log.error(
                "Transcription bot failed for room %s: %s",
                room,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(on_done)


async def stop_transcription(room: str) -> None:
    task = transcription_tasks.pop(room, None)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _room_has_callers(room: str) -> bool:
    """True when a real (non-bot) participant is still in the room.

    Fails safe: if the LiveKit API cannot be reached we report True so a
    temporary outage never wrongly frees a number that is actually in use.
    """
    try:
        async with lk.LiveKitAPI() as lkapi:
            response = await lkapi.room.list_participants(
                lk.ListParticipantsRequest(room=room)
            )
        return any(
            not participant.identity.startswith(BOT_IDENTITY_PREFIX)
            for participant in response.participants
        )
    except Exception:
        log.warning("could not check room %s; assuming it is still active", room)
        return True


async def _delete_room(room: str) -> None:
    """Force the LiveKit room closed so any stragglers get disconnected."""
    try:
        async with lk.LiveKitAPI() as lkapi:
            await lkapi.room.delete_room(lk.DeleteRoomRequest(room=room))
    except Exception:
        # Already gone is the expected case here.
        log.debug("room %s was already gone", room)


async def drop_call(room: str) -> None:
    """Forget a call and force its LiveKit room closed."""
    calls.pop(room, None)
    await stop_transcription(room)
    await _delete_room(room)


async def find_busy_room(number: str) -> str | None:
    """Return the live room `number` is in, pruning rooms that are gone.

    A call has no time limit: it lasts until someone leaves the room or the
    link drops. A registration is therefore only released when its LiveKit room
    no longer holds a real participant — which is what frees a number after an
    abnormal end (e.g. a network drop where the client never reached /end)
    instead of blocking it until a restart.
    """
    for room, info in list(calls.items()):
        if number not in (info["caller"], info["callee"]):
            continue

        # Skip the presence check briefly: a new call's room is legitimately
        # empty until the caller's client finishes joining.
        if time.monotonic() - info["created_at"] >= ROOM_CHECK_GRACE_SECONDS:
            if not await _room_has_callers(room):
                log.info("call %s has no participants left; releasing", room)
                await drop_call(room)
                continue

        return room
    return None


async def create_call_room(room: str) -> None:
    """Create the LiveKit room up front so its participant cap is enforced."""
    try:
        async with lk.LiveKitAPI() as lkapi:
            await lkapi.room.create_room(
                lk.CreateRoomRequest(
                    name=room,
                    max_participants=MAX_ROOM_PARTICIPANTS,
                )
            )
    except Exception:
        log.exception("Could not set the participant cap for room %s", room)


def lk_token(identity: str, room: str) -> str:
    return (
        lk.AccessToken(LK_KEY, LK_SECRET)
        .with_identity(identity)
        .with_grants(lk.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )

voip_calls = APIRouter(
    tags=["VOIP CALL"]
)


# --------------------------------------------------------------------------- #
# Hub: pushes events to the mobile apps (one or more sockets per identity)
# --------------------------------------------------------------------------- #
class Hub:
    def __init__(self) -> None:
        self.clients: dict[str, set[WebSocket]] = {}
 
    async def connect(self, identity: str, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.setdefault(identity, set()).add(ws)
 
    def disconnect(self, identity: str, ws: WebSocket) -> None:
        self.clients.get(identity, set()).discard(ws)
 
    async def send(self, identity: str, payload: dict) -> None:
        if not identity:
            return
        for ws in list(self.clients.get(identity, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(identity, ws)
 
 
hub = Hub()


def normalize_phone(number: str) -> str:
    """Normalize a phone number to E.164 so caller/callee identities match."""
    if not number:
        return ""
    digits = "".join(ch for ch in number if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("234"):
        return "+" + digits
    if digits.startswith("0"):
        return "+234" + digits[1:]
    if len(digits) == 10:
        return "+234" + digits
    return "+" + digits


@voip_calls.websocket("/ws/{identity}")
async def call_signaling(websocket: WebSocket, identity: str):
    """
    The mobile app connects here with its phone number as identity so the hub
    can push incoming-call events to the callee's device.
    """
    await hub.connect(normalize_phone(identity), websocket)
    try:
        while True:
            # The client only listens for events; keep the socket open.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(normalize_phone(identity), websocket)
 
@voip_calls.post("/call")
async def start_call(
    b: CallBody,
    auth_tok: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
        checking if the callee number exist in our db
    """
    # check_num = select()

    caller = normalize_phone(auth_tok.phone_number)
    callee = normalize_phone(b.callee)

    # One call at a time. Calls left behind by an abnormal end are detected and
    # released here, so a dropped call can no longer block a number.
    if await find_busy_room(caller):
        raise HTTPException(409, "you_are_busy")
    if await find_busy_room(callee):
        raise HTTPException(409, "line_busy")

    callee_account = db.execute(
        select(Account).where(Account.phone_number.in_(phone_variants(b.callee)))
    ).scalars().first()
    if callee_account is None:
        await send_invitation(callee, auth_tok.username)
        return {
            "status": "successful",
            "invitation_sent": True,
            "message": "This number is not registered. An invitation SMS has been sent.",
        }

    room = f"call-{uuid.uuid4().hex[:10]}"
    await create_call_room(room)
    raw_caller_lang = auth_tok.prefer_lang
    raw_callee_lang = callee_account.prefer_lang
    langs = {
        caller: stt_language(raw_caller_lang),
        callee: stt_language(raw_callee_lang),
    }
    # Show the DB value and the code it resolved to, so a wrong source language
    # is obvious immediately instead of looking like a translation bug.
    caller_model = STT_REGISTRY[langs[caller]].model_id
    callee_model = STT_REGISTRY[langs[callee]].model_id
    print(
        f"[call {room}] languages -> "
        f"Caller 1 {caller}: prefer_lang={raw_caller_lang!r} => stt={langs[caller]} "
        f"model={caller_model} | "
        f"Caller 2 {callee}: prefer_lang={raw_callee_lang!r} => stt={langs[callee]} "
        f"model={callee_model}",
        flush=True,
    )
    print(
        f"[call {room}] translation engine configured: {is_configured()}"
        + (
            ""
            if is_configured()
            else " (set NTLAS_TRANSLATE_URL in .env to translate between languages)"
        ),
        flush=True,
    )
    calls[room] = {
        "caller": caller,
        "callee": callee,
        "created_at": time.monotonic(),
    }
    start_transcription(room, caller, callee, langs)
    # Warm up only the two selected languages; this must not delay ringing, so
    # it runs in the background and the bot still loads lazily if it loses.
    warmup = asyncio.create_task(preload(langs.values()))
    _preload_tasks.add(warmup)
    warmup.add_done_callback(_preload_tasks.discard)
    await hub.send(
        callee,
        {
            "event": "incoming_call",
            "room": room,
            "caller": caller,
            "caller_name": auth_tok.username,
        },
    )
    return {"room": room, "token": lk_token(caller, room)}


@voip_calls.post("/call/{room}/accept")
async def accept_call(room: str, b: AcceptBody ,  auth_tok: Account = Depends(get_current_user)):
    c = calls.get(room)
    if not c or normalize_phone(b.identity) != c["callee"]:
        raise HTTPException(404, "call not found")
    await hub.send(c["caller"], {"event": "call_accepted", "room": room})
    return {"token": lk_token(normalize_phone(b.identity), room)}


@voip_calls.post("/call/{room}/decline")
async def decline_call(room: str):
    c = calls.get(room)
    # Drops the registration and forcibly closes the LiveKit room.
    await drop_call(room)
    if c:
        await hub.send(c["caller"], {"event": "call_declined", "room": room})
    return {"ok": True}


@voip_calls.post("/call/{room}/end")
async def end_call(room: str):
    c = calls.get(room)
    # Drops the registration and forcibly closes the LiveKit room.
    await drop_call(room)
    if c:
        for who in (c["caller"], c["callee"]):
            await hub.send(who, {"event": "call_ended", "room": room})
    return {"ok": True}