"""Which sentences the game can say, and where each one's audio clip lives.

The game never talks to the internet. Every sentence is generated once by
tools/generate_voice.py and stored as data/voice/<language>/<hash>.mp3; this
module is the single place that decides the list of sentences and the file
name for each, so the generator and the game always agree.
"""
from __future__ import annotations

import hashlib
from string import Formatter

from .paths import resource_path
from .tasks import ROUND_LENGTH

VOICE_FOLDER = "data/voice"


def normalise(text):
    return " ".join(str(text).split())


def clip_name(text):
    """File name for the clip of one sentence (stable hash of its text)."""
    return hashlib.sha1(normalise(text).encode("utf-8")).hexdigest()[:16] + ".mp3"


def clip_path(language, text):
    """Where the clip of a sentence lives. Looked up file by file, so a single
    clip placed next to the .exe overrides just that one packed clip."""
    return resource_path(f"{VOICE_FOLDER}/{language}/{clip_name(text)}")


def _round_end(strings, stars, total):
    """(fixed sentence, None) or (None, speech key) for a given score."""
    speech = strings.data.get("speech", {})
    exact = speech.get("round_end_exact")
    if isinstance(exact, dict) and total == ROUND_LENGTH and str(stars) in exact:
        return exact[str(stars)], None  # languages whose word forms depend on the number
    if stars == 1 and total > 1 and "round_end_one" in speech:
        return None, "round_end_one"
    if stars == total:
        return None, "round_end_perfect"
    return None, "round_end_good" if stars >= total * 0.6 else "round_end_ok"


def round_end_text(strings, stars, total):
    """The sentence spoken on the end screen for a given score."""
    text, key = _round_end(strings, stars, total)
    return text if key is None else strings.speech(key, stars=stars, total=total)


def miss_feedback(strings, outcome, hint_active):
    """What the game answers to a wrong click: (text shown, [sentences spoken]).

    Each sentence is its own pre-recorded clip, so they are spoken one after
    the other, in the order the language's pattern puts them on screen.
    """
    that_is = strings.speech("that_is", name=strings.area_name(outcome.clicked))
    if outcome.hint_started:
        pattern, parts = "hint_pattern", {"that_is": that_is, "hint": strings.speech("hint")}
    elif hint_active:
        return that_is, [that_is]
    elif outcome.zone_started:
        pattern, parts = "zone_pattern", {"that_is": that_is, "zone": strings.speech("zone")}
    else:
        phrase = strings.speech("close" if outcome.kind == "close" else "wrong")
        pattern, parts = "wrong_pattern", {"phrase": phrase, "that_is": that_is}
    raw = strings.data.get("speech", {}).get(pattern)
    try:
        order = [name for _, name, _, _ in Formatter().parse(raw) if name in parts]
    except (TypeError, ValueError):
        order = []
    if not order:  # no usable pattern: just say everything
        return " ".join(parts.values()), list(parts.values())
    return strings.speech(pattern, **parts), [parts[name] for name in order]


def all_lines(world, strings, tasks):
    """Every sentence the game may speak, without duplicates, in a stable order."""
    lines = []
    seen = set()

    def add(text):
        text = normalise(text)
        if text and text not in seen:
            seen.add(text)
            lines.append(text)

    # Phrases said as they are. An entry may be a list of variants, of which
    # the game picks one at random, so every variant needs its clip.
    for key in strings.data.get("speech", {}):
        if key == "that_is" or key.startswith("round_end") or key.endswith("_pattern"):
            continue  # filled in below, or only a pattern for the text on screen
        for phrase in strings.speech_variants(key):
            add(phrase)
    for task in tasks:
        add(strings.prompt(task))
    for stars in range(ROUND_LENGTH + 1):
        text, key = _round_end(strings, stars, ROUND_LENGTH)
        for phrase in [text] if key is None else strings.speech_variants(key, stars=stars, total=ROUND_LENGTH):
            add(phrase)
    # "That is ..." for everything a wrong click can land on.
    for area in [None] + list(world.countries) + list(world.oceans) + list(world.seas):
        for phrase in strings.speech_variants("that_is", name=strings.area_name(area)):
            add(phrase)
    return lines
