"""Access to data/strings.json: every displayed or spoken text of the game."""
from __future__ import annotations

import json
import random
from pathlib import Path

from .paths import resource_dirs, resource_path

STRINGS_FILE = "data/strings.json"   # English, the base language
BASE_LANGUAGE = "en"


def strings_file(language):
    """data/strings.json for English, data/strings.<code>.json for the others."""
    if not language or language == BASE_LANGUAGE:
        return STRINGS_FILE
    return f"data/strings.{language}.json"


def available_languages():
    """Language codes the game can be played in, English first."""
    codes = [BASE_LANGUAGE]
    for folder in resource_dirs("data"):
        for path in sorted(folder.glob("strings.*.json")):
            code = path.name.split(".")[1]
            if code not in codes:
                codes.append(code)
    return codes


class Strings:
    def __init__(self, data, rng=None):
        self.data = data
        self.language = data.get("language", "en")
        self._rng = rng or random.Random()
        self._bags = {}  # phrase key -> shuffled phrases still to use
        self._last = {}
        self._names = {k.lower(): v for k, v in data.get("names", {}).items()}

    @classmethod
    def load(cls, path=None, rng=None, language=None):
        path = Path(path) if path else resource_path(strings_file(language))
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh), rng)

    def _get(self, section, key):
        value = self.data.get(section, {}).get(key)
        return key if value is None else value

    def ui(self, key, **fmt):
        return self._format(self._get("ui", key), fmt)

    def speech(self, key, **fmt):
        """A spoken line. If the entry is a list, one phrase is picked."""
        value = self._get("speech", key)
        if isinstance(value, list):
            value = self._pick(key, value)
        return self._format(value, fmt)

    def speech_variants(self, key, **fmt):
        """Every phrasing ``speech(key)`` may return (one, unless the entry is a list)."""
        value = self.data.get("speech", {}).get(key)
        if value is None:
            return []
        return [self._format(phrase, fmt) for phrase in (value if isinstance(value, list) else [value])]

    @staticmethod
    def _format(text, fmt):
        try:
            return str(text).format(**fmt) if fmt else str(text)
        except (KeyError, IndexError, ValueError):
            return str(text)

    def _pick(self, key, phrases):
        """Rotate through the phrases in random order without repeating one
        until all were used, and never the same one twice in a row."""
        if not phrases:
            return ""
        bag = self._bags.get(key)
        if not bag:
            bag = list(phrases)
            self._rng.shuffle(bag)
            if len(bag) > 1 and bag[-1] == self._last.get(key):
                bag[0], bag[-1] = bag[-1], bag[0]
            self._bags[key] = bag
        phrase = bag.pop()
        self._last[key] = phrase
        return phrase

    def prompt(self, task):
        """The task's prompt in this language (English if not translated)."""
        return self.data.get("prompts", {}).get(task.id) or task.prompt

    def area_name(self, area):
        """How to say the name of a map area ('the Sahara desert', 'Germany')."""
        if area is None:
            return self.data.get("name_patterns", {}).get("unknown_water", "the sea")
        override = self._names.get(area.id.lower())
        if override:
            return override
        patterns = self.data.get("name_patterns", {})
        pattern = patterns.get(f"{area.kind}/{area.cls}") or patterns.get(area.kind) or "{name}"
        return self._format(pattern, {"name": area.name})
