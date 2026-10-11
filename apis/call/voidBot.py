"""Join each LiveKit call as a hidden participant and forward per-speaker STT.

Needs in .env:  LIVEKIT_URL (wss://<project>.livekit.cloud), LIVEKIT_API_KEY, LIVEKIT_API_SECRET
"""
import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from livekit import api as lk
from livekit import rtc
from livekit.agents.utils import http_context

from .providers import STTResult, STTSession, make_stt

log = logging.getLogger("bot")

TranscriptCallback = Callable[[str, STTResult, str], Awaitable[None]]


async def run_bot(
    room_name: str,
    langs: dict[str, str],
    on_transcript: TranscriptCallback,
    max_seconds: int = 900,
) -> None:
    """Listen to each participant's audio and forward their transcript."""
    lk_url = os.getenv("LIVEKIT_URL")
    lk_key = os.getenv("LIVEKIT_API_KEY")
    lk_secret = os.getenv("LIVEKIT_API_SECRET")
    if not lk_url or not lk_key or not lk_secret:
        raise RuntimeError("LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required")

    token = (
        lk.AccessToken(lk_key, lk_secret)
        .with_identity(f"transcriber-{room_name}")
        .with_grants(lk.VideoGrants(
            room_join=True, room=room_name,
            can_subscribe=True, can_publish=False, can_publish_data=False,
            hidden=True,
        ))
        .to_jwt()
    )

    room = rtc.Room()
    tasks: set[asyncio.Task] = set()
    done = asyncio.Event()
    connected = False

    async def listen(track: rtc.Track, who: str) -> None:
        lang = langs.get(who, "en")
        stream = None
        stt = None
        reader = None
        async with http_context.open():
            try:
                stt = make_stt(lang)
                # The STT session consumes 16 kHz mono PCM16 audio.
                stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
                await stt.start()
                reader = asyncio.create_task(forward_results(stt, who, lang))
                async for ev in stream:
                    await stt.send(bytes(ev.frame.data))
            except Exception:
                log.exception("audio loop failed for %s", who)
            finally:
                if stt is not None:
                    try:
                        await stt.close()
                    except Exception:
                        log.exception("could not close STT session for %s", who)
                if stream is not None:
                    try:
                        await stream.aclose()
                    except Exception:
                        log.exception("could not close audio stream for %s", who)
                if reader is not None:
                    try:
                        await reader
                    except Exception:
                        log.exception("transcription forwarding failed for %s", who)

    async def forward_results(stt: STTSession, who: str, lang: str) -> None:
        async for result in stt.results():
            if result.text.strip():
                await on_transcript(who, result, lang)

    def on_listener_done(task: asyncio.Task[None], identity: str) -> None:
        tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error:
            log.error(
                "Audio listener failed for %s: %s",
                identity,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    @room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication, participant: rtc.RemoteParticipant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        print(f"[bot] subscribed to audio from {participant.identity}", flush=True)
        t = asyncio.create_task(listen(track, participant.identity))
        tasks.add(t)
        t.add_done_callback(
            lambda completed, identity=participant.identity: on_listener_done(
                completed, identity
            )
        )

    @room.on("participant_disconnected")
    def on_left(participant: rtc.RemoteParticipant):
        print(f"[bot] {participant.identity} left", flush=True)
        if not room.remote_participants:
            done.set()

    try:
        await room.connect(lk_url, token)
        connected = True
        print(f"[bot] joined room {room_name}", flush=True)
        await asyncio.wait_for(done.wait(), timeout=max_seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if connected:
            await room.disconnect()
        print(f"[bot] left room {room_name}", flush=True)