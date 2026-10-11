"""Per-language speech-to-text for Nigerian languages.

Each language gets its own self-contained STT class. Only the class for the
language the caller selected is ever instantiated, and only that language's
Whisper weights are ever downloaded/loaded (lazily, then cached).

Whisper is not a streaming model, so "chunk by chunk" here means: detect speech
with a simple energy threshold, keep buffering until the speaker pauses,
transcribe that single utterance, emit the text, and repeat.

Public interface (unchanged for callers): STTResult, STTSession, make_stt().
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

log = logging.getLogger("stt")

# LiveKit hands us 16 kHz mono signed 16-bit PCM.
SAMPLE_RATE = 16_000

# How many bytes one sample takes (int16 mono).
_BYTES_PER_SAMPLE = 2


@dataclass
class STTResult:
    text: str
    is_final: bool


class STTSession(Protocol):
    async def start(self) -> None: ...

    async def send(self, pcm16_16k: bytes) -> None: ...

    async def close(self) -> None: ...

    def results(self) -> AsyncIterator[STTResult]: ...


# --------------------------------------------------------------------------- #
# Lazy model loading — nothing is loaded at import time.
# --------------------------------------------------------------------------- #
_MODEL_CACHE: dict[str, tuple[Any, Any]] = {}
_MODEL_CACHE_LOCK = threading.Lock()
_DEVICE: str | None = None


def _resolve_device() -> str:
    """Pick CUDA when available, otherwise CPU."""
    global _DEVICE
    if _DEVICE is None:
        import torch  # imported here so module import stays cheap

        _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    return _DEVICE


def _load_model(model_id: str) -> tuple[Any, Any]:
    """Load (and cache) a Whisper processor+model pair for one repo id.

    Runs under a lock because it is called from worker threads.
    """
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(model_id)
        if cached is None:
            from transformers import (
                WhisperForConditionalGeneration,
                WhisperProcessor,
            )

            token = os.getenv("HF_TOKEN") or None
            log.info("loading STT model %s", model_id)
            # NOTE: `token=` is the current transformers/huggingface_hub auth
            # argument. Older transformers used `use_auth_token=`.
            processor = WhisperProcessor.from_pretrained(model_id, token=token)
            model = WhisperForConditionalGeneration.from_pretrained(
                model_id, token=token
            )
            model.to(_resolve_device())
            model.eval()
            cached = (processor, model)
            _MODEL_CACHE[model_id] = cached
            log.info("loaded STT model %s on %s", model_id, _resolve_device())
        return cached


def loaded_models() -> tuple[str, ...]:
    """Repo ids currently in memory. Used by tests to prove isolation."""
    return tuple(sorted(_MODEL_CACHE))


def _frame_ms(pcm: bytes) -> float:
    """Duration of a PCM16 mono buffer in milliseconds."""
    return (len(pcm) / _BYTES_PER_SAMPLE) * 1000.0 / SAMPLE_RATE


# --------------------------------------------------------------------------- #
# Shared chunking / segmentation base class
# --------------------------------------------------------------------------- #
class BaseChunkedSTT:
    """Energy-based utterance segmentation on top of a non-streaming model.

    Subclasses set `lang_code` / `model_id` and, if needed, override the
    thresholds below at class level.
    """

    lang_code: str = ""
    model_id: str = ""

    # Mean absolute amplitude (int16 scale) above which a frame counts as speech.
    SPEECH_THRESHOLD: int = 500
    # Audio kept before speech starts so the first syllable is not clipped.
    PRE_ROLL_MS: int = 200
    # Silence needed to consider the utterance finished.
    SILENCE_MS: int = 700
    # Hard cut: never let one utterance grow past this.
    MAX_UTTERANCE_MS: int = 12_000
    # Utterances with less real speech than this are noise, not words.
    MIN_SPEECH_MS: int = 400

    def __init__(self, lang: str | None = None) -> None:
        self.lang = lang or self.lang_code
        self._queue: asyncio.Queue[STTResult | Exception | None] = asyncio.Queue()
        # Serialises transcription so results keep their speaking order.
        self._lock = asyncio.Lock()
        self._pending: set[asyncio.Task[None]] = set()
        self._buffer = bytearray()
        self._pre_roll: deque[tuple[bytes, float]] = deque()
        self._pre_roll_ms = 0.0
        self._utterance_ms = 0.0
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._in_speech = False
        self._started = False
        self._closed = False

    # ---- model access ---------------------------------------------------- #

    def get_model(self) -> tuple[Any, Any]:
        """Return this language's (processor, model), loading it on first use."""
        return _load_model(self.model_id)

    # ---- transcription (the bit tests replace) ---------------------------- #

    def transcribe_audio(self, pcm16_16k: bytes) -> str:
        """Transcribe one utterance. Subclasses share this implementation."""
        import numpy as np
        import torch

        processor, model = self.get_model()
        audio = np.frombuffer(pcm16_16k, dtype=np.int16).astype(np.float32)
        audio /= 32768.0  # int16 -> float32 in [-1, 1]

        inputs = processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        input_features = inputs.input_features.to(_resolve_device())
        with torch.no_grad():
            predicted_ids = model.generate(input_features)
        return processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

    # ---- public session interface ---------------------------------------- #

    async def start(self) -> None:
        self._started = True

    async def send(self, pcm16_16k: bytes) -> None:
        if not self._started:
            raise RuntimeError("STT session has not been started")
        if self._closed or not pcm16_16k:
            return
        self._feed(pcm16_16k)

    async def close(self) -> None:
        """Flush the in-progress utterance, drain transcriptions, end results."""
        if self._closed:
            return
        self._closed = True
        if self._in_speech:
            self._flush_utterance()
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)
        await self._queue.put(None)

    async def results(self) -> AsyncIterator[STTResult]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    # ---- chunking -------------------------------------------------------- #

    def _feed(self, pcm: bytes) -> None:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16)
        if samples.size == 0:
            return

        duration_ms = _frame_ms(pcm)
        is_speech = float(np.abs(samples).mean()) >= self.SPEECH_THRESHOLD

        if not self._in_speech:
            if not is_speech:
                # Hold recent quiet audio so a burst is not clipped at the
                # front; keep the window to roughly PRE_ROLL_MS.
                self._pre_roll.append((pcm, duration_ms))
                self._pre_roll_ms += duration_ms
                while self._pre_roll and self._pre_roll_ms > self.PRE_ROLL_MS:
                    _, dropped_ms = self._pre_roll.popleft()
                    self._pre_roll_ms -= dropped_ms
                return

            # Speech just started. Replay the pre-roll that came *before* this
            # frame, then add the current frame exactly once.
            self._in_speech = True
            self._buffer = bytearray()
            self._utterance_ms = 0.0
            self._speech_ms = 0.0
            self._silence_ms = 0.0
            for frame, frame_ms in self._pre_roll:
                self._buffer.extend(frame)
                self._utterance_ms += frame_ms
            self._pre_roll.clear()
            self._pre_roll_ms = 0.0
            self._buffer.extend(pcm)
            self._utterance_ms += duration_ms
            self._speech_ms += duration_ms
            return

        self._buffer.extend(pcm)
        self._utterance_ms += duration_ms
        if is_speech:
            self._speech_ms += duration_ms
            self._silence_ms = 0.0
        else:
            self._silence_ms += duration_ms

        if self._silence_ms >= self.SILENCE_MS or self._utterance_ms >= self.MAX_UTTERANCE_MS:
            self._flush_utterance()

    def _reset_utterance(self) -> None:
        self._buffer = bytearray()
        self._pre_roll.clear()
        self._pre_roll_ms = 0.0
        self._utterance_ms = 0.0
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._in_speech = False

    def _flush_utterance(self) -> None:
        """Emit the buffered utterance for transcription if it holds speech."""
        pcm = bytes(self._buffer)
        speech_ms = self._speech_ms
        self._reset_utterance()

        # Too short / mostly silence -> background noise, not an utterance.
        if speech_ms < self.MIN_SPEECH_MS:
            return

        task = asyncio.create_task(self._transcribe(pcm))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _transcribe(self, pcm: bytes) -> None:
        try:
            # to_thread keeps the event loop free while Whisper works.
            async with self._lock:
                text = await asyncio.to_thread(self.transcribe_audio, pcm)
        except Exception as error:  # surfaced through results()
            log.exception("transcription failed for %s", self.lang_code or self.lang)
            await self._queue.put(error)
            return

        text = (text or "").strip()
        if text:
            await self._queue.put(STTResult(text, True))


# --------------------------------------------------------------------------- #
# One class per language — each owns its own repo id and settings.
# --------------------------------------------------------------------------- #
class YorubaSTT(BaseChunkedSTT):
    lang_code = "yo"
    model_id = "NCAIR1/Yoruba-ASR"


class IgboSTT(BaseChunkedSTT):
    lang_code = "ig"
    model_id = "NCAIR1/Igbo-ASR"


class HausaSTT(BaseChunkedSTT):
    lang_code = "ha"
    model_id = "NCAIR1/Hausa-ASR"


class EnglishSTT(BaseChunkedSTT):
    """Nigerian-accented English."""

    lang_code = "en"
    model_id = "NCAIR1/NigerianAccentedEnglish"


class PidginSTT(EnglishSTT):
    """Nigerian Pidgin.

    KNOWN LIMITATION: no Pidgin ASR model exists, so this reuses the
    Nigerian-accented English model. Pidgin accuracy will be lower than the
    dedicated per-language models above.
    """

    lang_code = "pcm"


# --------------------------------------------------------------------------- #
# Registry + factory
# --------------------------------------------------------------------------- #
STT_REGISTRY: dict[str, type[BaseChunkedSTT]] = {
    "yo": YorubaSTT,
    "ig": IgboSTT,
    "ha": HausaSTT,
    "en": EnglishSTT,
    "pcm": PidginSTT,
}

SUPPORTED_LANGUAGES: tuple[str, ...] = tuple(STT_REGISTRY)


def make_stt(lang: str) -> STTSession:
    """Create the STT session for exactly one language.

    Raises:
        ValueError: if the code is not supported (message lists the codes).
    """
    code = (lang or "").strip().lower()
    cls = STT_REGISTRY.get(code)
    if cls is None:
        raise ValueError(
            f"Unsupported STT language {lang!r}. "
            f"Supported codes: {', '.join(sorted(STT_REGISTRY))}"
        )
    return cls(code)


async def preload(langs: Iterable[str]) -> None:
    """Load models for only the languages passed in (never any others).

    Loading happens in a worker thread so the event loop is not blocked.
    """
    unique = {(lang or "").strip().lower() for lang in langs}
    for code in unique:
        cls = STT_REGISTRY.get(code)
        if cls is None:
            log.warning("skipping preload for unsupported language %r", code)
            continue
        session = cls(code)
        try:
            await asyncio.to_thread(session.get_model)
        except Exception:
            log.exception("could not preload STT model for %s", code)
