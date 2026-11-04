# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Spell numbers and temperature units as words before speech synthesis.

Pocket TTS reads digit strings poorly ("176" as "seventeen six"), so every
spoken text passes through :func:`speakable`. Displayed text keeps its digits.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))

_UNIT = r"\s*(?:°|º)\s*(?P<unit>[FfCc])\b|\s*(?:°|º)"
_NUMBER = re.compile(
    r"(?<![\w.])(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?(?![\w])(?P<suffix>" + _UNIT + r"|\s*%)?"
)


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    words = [f"{_ONES[hundreds]} hundred"] if hundreds else []
    if rest >= 20:
        tens, ones = divmod(rest, 10)
        words.append(_TENS[tens] + (f"-{_ONES[ones]}" if ones else ""))
    elif rest or not hundreds:
        words.append(_ONES[rest])
    return " ".join(words)


def _integer_words(n: int) -> str:
    if n < 1000:
        return _below_thousand(n)
    words = []
    for scale, name in _SCALES:
        count, n = divmod(n, scale)
        if count:
            words.append(f"{_integer_words(count)} {name}")
    if n:
        words.append(_below_thousand(n))
    return " ".join(words)


def _replace(match: re.Match[str]) -> str:
    words = _integer_words(int(match["int"].replace(",", "")))
    if match["frac"]:
        words += " point " + " ".join(_ONES[int(digit)] for digit in match["frac"])
    suffix = match["suffix"] or ""
    if "%" in suffix:
        return f"{words} percent"
    if suffix:
        unit = {"f": " Fahrenheit", "c": " Celsius"}.get((match["unit"] or "").lower(), "")
        return f"{words} degrees{unit}"
    return words


def speakable(text: str) -> str:
    """Return *text* with numbers, degree signs and percentages spelled as words."""
    return _NUMBER.sub(_replace, text)


class _SpokenNumbersTTS:
    """Delegate to a TTS client after spelling numbers in the text to synthesize."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def synthesize(self, text: str, **kwargs: Any) -> bytes:
        return await self._inner.synthesize(speakable(text), **kwargs)

    async def health(self) -> bool:
        return await self._inner.health()

    async def close(self) -> None:
        await self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _SpokenNumbersStreamingTTS(_SpokenNumbersTTS):
    """Streaming variant; defined separately so non-streaming clients stay non-streaming."""

    def stream(self, text: str, **kwargs: Any) -> AsyncIterator[Any]:
        return self._inner.stream(speakable(text), **kwargs)


def spoken_numbers(tts: Any) -> _SpokenNumbersTTS:
    """Wrap *tts*, keeping its streaming capability."""
    return _SpokenNumbersStreamingTTS(tts) if callable(getattr(tts, "stream", None)) else _SpokenNumbersTTS(tts)
