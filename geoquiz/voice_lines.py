"""Which sentences the game can say, and where each one's audio clip lives.

The game never talks to the internet. Every sentence is generated once by
tools/generate_voice.py and stored as data/voice/<language>/<hash>.mp3; this
module is the single place that decides the list of sentences and the file
name for each, so the generator and the game always agree.
"""
from __future__ import annotations

import hashlib

from .paths import resource_path
from .tasks import ROUND_LENGTH

VOICE_FOLDER = "data/voice"


def normalise(text):
    return " ".join(str(text).split())


def clip_name(text):
    """File name for the clip of one sentence (stable hash of its text)."""
    return hashlib.sha1(normalise(text).encode("utf-8")).hexdigest()[:16] + ".mp3"


def voice_dir(language):
    return resource_path(f"{VOICE_FOLDER}/{language}")


def round_end_text(strings, stars, total):
    """The sentence spoken on the end screen for a given score."""
    exact = strings.data.get("speech", {}).get("round_end_exact")
    if isinstance(exact, dict) and total == ROUND_LENGTH and str(stars) in exact:
        return exact[str(stars)]  # languages whose word forms depend on the number
    if stars == 1 and total > 1 and "round_end_one" in strings.data.get("speech", {}):
        key = "round_end_one"
    elif stars == total:
        key = "round_end_perfect"
    elif stars >= total * 0.6:
        key = "round_end_good"
    else:
        key = "round_end_ok"
    return strings.speech(key, stars=stars, total=total)


def all_lines(world, strings, tasks):
    """Every sentence the game may speak, without duplicates, in a stable order."""
    lines = []
    seen = set()

    def add(text):
        text = normalise(text)
        if text and text not in seen:
            seen.add(text)
            lines.append(text)

    speech = strings.data.get("speech", {})
    for key in ("welcome", "praise", "close", "wrong", "zone", "hint", "after_hint"):
        value = speech.get(key, [])
        for phrase in (value if isinstance(value, list) else [value]):
            add(phrase)
    for task in tasks:
        add(strings.prompt(task))
    for stars in range(ROUND_LENGTH + 1):
        add(round_end_text(strings, stars, ROUND_LENGTH))
    # "That is ..." for everything a wrong click can land on.
    add(strings.speech("that_is", name=strings.area_name(None)))
    for area in list(world.countries) + list(world.oceans) + list(world.seas):
        add(strings.speech("that_is", name=strings.area_name(area)))
    return lines
