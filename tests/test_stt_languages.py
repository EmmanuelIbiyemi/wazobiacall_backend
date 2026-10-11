"""Tests for the per-language STT providers (no torch/transformers needed).

Run:  python tests/test_stt_languages.py

Proves three things:
  (a) only the selected language's class is created,
  (b) no other language's model is ever loaded,
  (c) each speech burst produces exactly one result.

The transcriber is replaced with a fake so the real Whisper weights are never
downloaded, and the model loader is replaced with a recorder so we can see
exactly which repo ids would have been fetched.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np

# Load the provider modules straight from their files. `apis.call.__init__`
# imports the DB/router stack (psycopg2 and friends), which the STT layer does
# not need, so importing through the package would drag it in for no reason.
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "apis" / "call"


def _load_module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, PACKAGE_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


providers = _load_module("call_providers", "providers.py")
tts = _load_module("call_tts", "tts.py")

EnglishSTT = providers.EnglishSTT
HausaSTT = providers.HausaSTT
IgboSTT = providers.IgboSTT
PidginSTT = providers.PidginSTT
YorubaSTT = providers.YorubaSTT
make_stt = providers.make_stt

SAMPLE_RATE = 16_000
FRAME_MS = 10
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 160 samples


def frames(amplitude: int, duration_ms: int) -> list[bytes]:
    """Build `duration_ms` of mono int16 PCM in ~10 ms frames."""
    rng = np.random.default_rng(amplitude)
    total = int(SAMPLE_RATE * duration_ms / 1000)
    wave = rng.integers(-amplitude, amplitude + 1, size=total, dtype=np.int16)
    return [
        wave[start : start + FRAME_SAMPLES].tobytes()
        for start in range(0, total, FRAME_SAMPLES)
    ]


class RecordingSTT(YorubaSTT):
    """Yoruba class with the transcribe step faked, as the spec allows."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[int] = []

    def transcribe_audio(self, pcm16_16k: bytes) -> str:
        self.calls.append(len(pcm16_16k))
        return f"utterance-{len(self.calls)}"


class FakeLoader:
    """Stands in for providers._load_model and records requested repo ids."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def __call__(self, model_id: str):
        self.requested.append(model_id)
        return ("fake-processor", "fake-model")


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"{'PASS' if condition else 'FAIL'}: {label}{f' -> {detail}' if detail else ''}")
    return condition


async def test_chunking() -> bool:
    """(c) Each burst becomes exactly one result."""
    print("\n[1] chunk-by-chunk segmentation")
    providers._MODEL_CACHE.clear()

    stt = RecordingSTT()
    await stt.start()

    # 3 bursts of 1.0 s speech separated by 1.0 s of silence. The silence is
    # longer than SILENCE_MS (700 ms), so each burst is one utterance.
    for _ in range(3):
        for frame in frames(3000, 1000):
            await stt.send(frame)
        for frame in frames(0, 1000):
            await stt.send(frame)

    await stt.close()
    results = [r async for r in stt.results()]

    ok = check("3 bursts -> 3 results", len(results) == 3, f"got {len(results)}")
    ok &= check("transcriber called once per burst", len(stt.calls) == 3)
    ok &= check(
        "results keep speaking order",
        [r.text for r in results] == ["utterance-1", "utterance-2", "utterance-3"],
        str([r.text for r in results]),
    )
    ok &= check("every result is final", all(r.is_final for r in results))
    ok &= check("no model was loaded", providers.loaded_models() == ())

    # Byte-exact buffering: burst 1 is 1.0 s speech + 0.7 s trailing silence,
    # bursts 2-3 also carry 0.2 s of pre-roll. This catches duplicated frames.
    def ms_to_bytes(ms: int) -> int:
        return ms * SAMPLE_RATE // 1000 * 2

    expected_sizes = [ms_to_bytes(1700), ms_to_bytes(1900), ms_to_bytes(1900)]
    ok &= check(
        "buffered audio is pre-roll + speech + cut silence, no duplicates",
        stt.calls == expected_sizes,
        f"got {stt.calls}, expected {expected_sizes}",
    )
    return ok


async def test_short_burst_ignored() -> bool:
    """Speech under MIN_SPEECH_MS must not be emitted."""
    print("\n[2] short noise bursts are ignored")
    providers._MODEL_CACHE.clear()

    stt = RecordingSTT()
    await stt.start()
    for frame in frames(3000, 200):  # 200 ms < 400 ms minimum
        await stt.send(frame)
    for frame in frames(0, 1000):
        await stt.send(frame)
    await stt.close()
    results = [r async for r in stt.results()]
    return check("200 ms burst dropped", len(results) == 0, f"got {len(results)}")


async def test_quiet_audio_is_silent() -> bool:
    """Pure silence must not create utterances."""
    print("\n[3] silence produces nothing")

    stt = RecordingSTT()
    await stt.start()
    for frame in frames(0, 3000):
        await stt.send(frame)
    await stt.close()
    results = [r async for r in stt.results()]
    return check("silence -> 0 results", len(results) == 0, f"got {len(results)}")


def test_factory_isolation() -> bool:
    """(a) make_stt creates only the selected language's class."""
    print("\n[4] factory creates only the selected class")

    expected = {
        "yo": YorubaSTT,
        "ig": IgboSTT,
        "ha": HausaSTT,
        "en": EnglishSTT,
        "pcm": PidginSTT,
    }
    ok = True
    for code, cls in expected.items():
        session = make_stt(code)
        ok &= check(
            f"make_stt({code!r}) -> {cls.__name__}",
            type(session) is cls,
            type(session).__name__,
        )

    # Creating a session must not load anything.
    ok &= check("creating sessions loaded no model", providers.loaded_models() == ())

    # Unsupported code must fail loudly and list the supported ones.
    try:
        make_stt("fr")
        ok &= check("unsupported code raises ValueError", False, "no error raised")
    except ValueError as error:
        message = str(error)
        ok &= check(
            "unsupported code raises ValueError",
            "Supported codes" in message and "yo" in message and "pcm" in message,
            message,
        )

    # Only the selected language's repo id is requested.
    print("\n[5] only the selected language's model is fetched")
    loader = FakeLoader()
    original = providers._load_model
    providers._load_model = loader  # type: ignore[assignment]
    try:
        session = make_stt("ha")
        session.get_model()
        ok &= check(
            "only Hausa repo requested",
            loader.requested == [HausaSTT.model_id],
            str(loader.requested),
        )
        ok &= check(
            "no Yoruba/Igbo/English/Pidgin repo requested",
            not any(
                other.model_id in loader.requested
                for other in (YorubaSTT, IgboSTT, EnglishSTT, PidginSTT)
            ),
            str(loader.requested),
        )
    finally:
        providers._load_model = original  # type: ignore[assignment]

    return ok


def test_model_ids_are_distinct() -> bool:
    """Each language points at its own repo (Pidgin intentionally shares en)."""
    print("\n[6] per-language model ids")
    ok = check("Yoruba repo", YorubaSTT.model_id == "NCAIR1/Yoruba-ASR", YorubaSTT.model_id)
    ok &= check("Igbo repo", IgboSTT.model_id == "NCAIR1/Igbo-ASR", IgboSTT.model_id)
    ok &= check("Hausa repo", HausaSTT.model_id == "NCAIR1/Hausa-ASR", HausaSTT.model_id)
    ok &= check(
        "English repo",
        EnglishSTT.model_id == "NCAIR1/NigerianAccentedEnglish",
        EnglishSTT.model_id,
    )
    ok &= check(
        "Pidgin reuses the English model (known limitation)",
        PidginSTT.model_id == EnglishSTT.model_id,
        PidginSTT.model_id,
    )
    ok &= check(
        "supported codes",
        providers.SUPPORTED_LANGUAGES == ("yo", "ig", "ha", "en", "pcm"),
        str(providers.SUPPORTED_LANGUAGES),
    )
    return ok


async def test_tts_registry() -> bool:
    """TTS mirrors the STT layout and stubs every voice."""
    print("\n[7] TTS mirrors the STT structure")

    ok = check(
        "same language coverage",
        tuple(tts.TTS_REGISTRY) == providers.SUPPORTED_LANGUAGES,
        str(tuple(tts.TTS_REGISTRY)),
    )
    voice = tts.make_tts("yo")
    ok &= check("make_tts(yo) -> YorubaTTS", type(voice) is tts.YorubaTTS)
    ok &= check(
        "stub synthesize returns None",
        await voice.synthesize("bawo ni") is None,
    )
    try:
        tts.make_tts("de")
        ok &= check("unsupported TTS code raises", False, "no error raised")
    except ValueError as error:
        ok &= check("unsupported TTS code raises", "Supported codes" in str(error))
    return ok


async def main() -> int:
    results = [
        await test_chunking(),
        await test_short_burst_ignored(),
        await test_quiet_audio_is_silent(),
        test_factory_isolation(),
        test_model_ids_are_distinct(),
        await test_tts_registry(),
    ]
    print()
    if all(results):
        print("ALL TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
