"""Per-language text-to-speech, mirroring the STT provider layout.

Same shape as `providers.py`: a shared base class, one class per language, a
registry, and a factory (`make_tts`). The voice provider is not chosen yet, so
every `synthesize()` is a stub that returns `None`.
"""

from __future__ import annotations

import logging

log = logging.getLogger("tts")


class BaseTTS:
    """Base class every language voice implements.

    `synthesize` is deliberately the only hard requirement, so swapping in a
    real provider later means editing one method per language.
    """

    lang_code: str = ""
    # Voice/model handle for the provider once it is picked.
    voice: str | None = None

    def __init__(self, lang: str | None = None) -> None:
        self.lang = lang or self.lang_code

    async def synthesize(self, text: str) -> bytes | None:
        """Turn text into speakable audio bytes. Returns None while unset."""
        raise NotImplementedError


class YorubaTTS(BaseTTS):
    lang_code = "yo"

    async def synthesize(self, text: str) -> bytes | None:
        # TODO: wire the Yoruba voice provider here.
        return None


class IgboTTS(BaseTTS):
    lang_code = "ig"

    async def synthesize(self, text: str) -> bytes | None:
        # TODO: wire the Igbo voice provider here.
        return None


class HausaTTS(BaseTTS):
    lang_code = "ha"

    async def synthesize(self, text: str) -> bytes | None:
        # TODO: wire the Hausa voice provider here.
        return None


class EnglishTTS(BaseTTS):
    lang_code = "en"

    async def synthesize(self, text: str) -> bytes | None:
        # TODO: wire the Nigerian English voice provider here.
        return None


class PidginTTS(BaseTTS):
    lang_code = "pcm"

    async def synthesize(self, text: str) -> bytes | None:
        # TODO: wire the Nigerian Pidgin voice provider here.
        return None


TTS_REGISTRY: dict[str, type[BaseTTS]] = {
    "yo": YorubaTTS,
    "ig": IgboTTS,
    "ha": HausaTTS,
    "en": EnglishTTS,
    "pcm": PidginTTS,
}

SUPPORTED_LANGUAGES: tuple[str, ...] = tuple(TTS_REGISTRY)


def make_tts(lang: str) -> BaseTTS:
    """Create the TTS voice for exactly one language.

    Raises:
        ValueError: if the code is not supported (message lists the codes).
    """
    code = (lang or "").strip().lower()
    cls = TTS_REGISTRY.get(code)
    if cls is None:
        raise ValueError(
            f"Unsupported TTS language {lang!r}. "
            f"Supported codes: {', '.join(sorted(TTS_REGISTRY))}"
        )
    return cls(code)
