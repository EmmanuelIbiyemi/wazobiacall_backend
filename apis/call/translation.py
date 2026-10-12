"""Translate what one call party says into the other party's language.

This is the single seam the call pipeline uses. Both languages come from the
database (`Account.prefer_lang`): the speaker's own language is the STT source,
and the *other* party's language is the translation target.

Translation is handled by NTLAS (the external engine). Point it at the engine:

    NTLAS_TRANSLATE_URL=https://your-ntlas-host/translate

It is called as:

    POST <url>   {"text": "...", "source": "en", "target": "yo"}

and may reply with either {"translated": "..."} or {"text": "..."}.
Without it, text passes through unchanged so calls still work.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("translate")

TRANSLATE_URL = os.getenv("NTLAS_TRANSLATE_URL", "").strip()
TRANSLATE_TIMEOUT_SECONDS = 10.0

# Warn once per process so a long call does not flood the terminal.
_warned = False


def is_configured() -> bool:
    """True when the NTLAS translation endpoint is wired up."""
    return bool(TRANSLATE_URL)


async def translate(text: str, source_lang: str, target_lang: str) -> str:
    """Translate `text` from `source_lang` into `target_lang` via NTLAS.

    Returns `text` unchanged when there is nothing to do, or when no engine is
    configured / the engine fails.
    """
    text = (text or "").strip()
    # Nothing to translate when there is no text or both parties match.
    if not text or source_lang == target_lang:
        return text

    global _warned
    if not is_configured():
        if not _warned:
            _warned = True
            log.warning(
                "NTLAS_TRANSLATE_URL is not set; text passes through "
                "untranslated. Set it in .env to enable translation."
            )
        return text

    try:
        async with httpx.AsyncClient(timeout=TRANSLATE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                TRANSLATE_URL,
                json={"text": text, "source": source_lang, "target": target_lang},
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        # Never break a live call because the engine is unreachable.
        log.exception("translation failed; falling back to the original text")
        return text

    translated = data.get("translated") or data.get("text") or ""
    translated = str(translated).strip()
    return translated or text
