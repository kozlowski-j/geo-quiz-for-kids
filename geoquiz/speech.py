"""Speech from pre-recorded clips (generated once with ElevenLabs).

Every sentence the game can say has an mp3 in data/voice/<language>/, named
after a hash of its text (see voice_lines.py). ``say()`` just starts the
right clip on a dedicated mixer channel and returns at once, so the game
loop never waits. A new utterance interrupts the current one unless
``interrupt=False`` is passed, in which case it is queued behind it.

A sentence without a clip is skipped silently (it is always shown as text
too) and remembered in ``missing``; run tools/generate_voice.py to create it.
"""
from __future__ import annotations

from collections import deque

from .paths import resource_dirs
from .voice_lines import VOICE_FOLDER, clip_path, normalise

GAP_MS = 120  # short pause between two sentences spoken in a row


class Speaker:
    def __init__(self, language="en", enabled=True, volume=1.0):
        self.language = language or "en"
        self.available = False
        self.voice_name = ""
        self.error = ""
        self.history = []      # every utterance handed to say(), for tests and debugging
        self.missing = set()   # sentences that had no clip
        self._queue = deque()  # clips waiting for the current one to finish
        self._sounds = {}      # file name -> loaded Sound
        self._channel = None
        self._mixer = None
        self._resume_at = None  # when the next queued clip may start
        self._chained = False   # a clip of the current utterance has already played
        if not enabled:
            return
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.set_reserved(1)  # channel 0 belongs to the voice
            self._channel = pygame.mixer.Channel(0)
            self._channel.set_volume(volume)
            self._mixer = pygame
        except Exception as exc:  # no audio device
            self.error = f"{type(exc).__name__}: {exc}"
            return
        self.set_language(self.language)

    def set_language(self, language):
        """Switch to the clips of another language (data/voice/<language>/)."""
        self.language = language or "en"
        if self._channel is None:
            return
        self.stop()
        self._sounds.clear()
        folder = f"{VOICE_FOLDER}/{self.language}"
        count = len({path.name for d in resource_dirs(folder) for path in d.glob("*.mp3")})
        self.available = count > 0
        self.voice_name = f"{count} recorded clips ({self.language})"
        self.error = "" if count else f"no voice clips in {folder}"

    # ---- public API ----------------------------------------------------------
    def say(self, text, interrupt=True):
        """Speak a sentence, or a list of sentences one after the other."""
        parts = [text] if isinstance(text, str) or text is None else list(text)
        parts = [p for p in (normalise(p) for p in parts if p) if p]
        if not parts:
            return
        self.history.append(" ".join(parts))
        if not self.available:
            return
        sounds = [s for s in (self._load(p) for p in parts) if s is not None]
        if interrupt:
            self._queue.clear()
            self._channel.stop()
            self._resume_at = None
            self._chained = False
        self._queue.extend(sounds)
        self.update()

    def stop(self):
        self._queue.clear()
        if self._channel is not None:
            self._channel.stop()

    @property
    def busy(self):
        """True while something is being spoken or waiting to be spoken."""
        if not self.available:
            return False
        return bool(self._queue) or self._channel.get_busy()

    def update(self):
        """Start the next queued clip when the current one has finished.
        Called every frame by the game."""
        if not self.available or not self._queue or self._channel.get_busy():
            return
        now = self._mixer.time.get_ticks()
        if self._resume_at is None:  # the channel has just gone quiet
            self._resume_at = now + (GAP_MS if self._chained else 0)
        if now >= self._resume_at:
            self._channel.play(self._queue.popleft())
            self._chained = True
            self._resume_at = None

    # ---- internals -------------------------------------------------------------
    def _load(self, sentence):
        path = clip_path(self.language, sentence)
        name = path.name
        if name in self._sounds:
            return self._sounds[name]
        sound = None
        if path.exists():
            try:
                sound = self._mixer.mixer.Sound(str(path))
            except Exception as exc:
                self.error = f"{path.name}: {exc}"
        if sound is None:
            self.missing.add(sentence)
        if len(self._sounds) > 300:
            self._sounds.clear()
        self._sounds[name] = sound
        return sound
