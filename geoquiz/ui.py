"""The pygame user interface: start screen, play screen, end screen.

Game rules live in tasks.py and map maths in mapdata.py / view.py; this file
only turns mouse input into calls on those and draws the result. Shapes,
fonts and colours come from gfx.py and maprender.py.
"""
from __future__ import annotations

import array
import math
import random
import time

import pygame

from . import gfx
from .gfx import INK, INK_SOFT, WHITE, GOLD, EMPTY
from .mapdata import WorldMap
from .maprender import MapRenderer, OCEAN_TOP, OCEAN_BOTTOM
from .paths import progress_path
from .speech import Speaker
from .strings import BASE_LANGUAGE, Strings, available_languages
from .tasks import Progress, Round, collection, load_tasks, select_round, ROUND_LENGTH
from .view import Viewport
from .voice_lines import round_end_text

FPS = 60
DRAG_THRESHOLD_PX = 8        # moving the mouse farther than this while pressed is a drag
ZOOM_STEP = 1.25
CELEBRATION_MIN_SECONDS = 1.6
CELEBRATION_MAX_SECONDS = 7.0
BANNER_SECONDS = 5.0
PICTURE_SECONDS = 2.8        # how long the big picture is shown when a task starts
PICTURE_SHRINK_SECONDS = 0.45  # ...the last part of which it shrinks into the top bar

BLUE = (74, 137, 255)
ORANGE = (255, 152, 67)
RED = (255, 110, 110)
GREEN = (46, 196, 130)
SOFT = (255, 255, 255)       # "quiet" buttons: white with dark text
LEVEL_COLORS = [(46, 196, 130), (255, 152, 67), (240, 98, 146)]
HELPED = (170, 200, 245)     # marker for a task that needed the answer shown
CONFETTI = [(255, 107, 129), (255, 198, 52), (46, 196, 130), (74, 137, 255),
            (168, 130, 255), (255, 152, 67), (94, 214, 220)]

MENU, PLAY, END = "menu", "play", "end"


def make_chime():
    """A short rising three-note chime, synthesised so no sound file is needed."""
    rate = 44100
    samples = array.array("h")
    for start, freq in ((0.0, 523.25), (0.11, 659.25), (0.22, 783.99)):
        n0 = int(start * rate)
        length = int(0.45 * rate)
        while len(samples) < n0 + length:
            samples.append(0)
        for i in range(length):
            t = i / rate
            env = min(1.0, t / 0.01) * math.exp(-t * 7.0)
            v = math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(4 * math.pi * freq * t)
            samples[n0 + i] = max(-32000, min(32000, samples[n0 + i] + int(v * env * 7000)))
    return pygame.mixer.Sound(buffer=samples.tobytes())


class Button:
    """A flat pill button. ``color`` SOFT gives a white button with dark text."""

    def __init__(self, key, rect, label="", color=BLUE, icon=None):
        self.key = key
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color
        self.icon = icon

    def draw(self, screen, font, hovered):
        rect = self.rect.move(0, -2) if hovered else self.rect
        quiet = self.color == SOFT
        if quiet:
            color = (240, 245, 255) if hovered else SOFT
            ink = INK
        else:
            color = gfx.lighten(self.color, 0.12) if hovered else self.color
            ink = WHITE
        gfx.draw_panel(screen, rect, color, rect.height // 2, shadow=max(4, rect.height // 9),
                       gradient=0.0 if quiet else 0.14)
        text = font.render(self.label, True, ink) if self.label else None
        icon_size = int(rect.height * (0.46 if text else 0.5)) if self.icon else 0
        gap = int(rect.height * 0.16) if (self.icon and text) else 0
        total = icon_size + gap + (text.get_width() if text else 0)
        x = rect.centerx - total // 2
        if self.icon:
            screen.blit(gfx.icon(self.icon, icon_size, ink), (x, rect.centery - icon_size // 2))
            x += icon_size + gap
        if text:
            screen.blit(text, (x, rect.centery - text.get_height() // 2))


class App:
    def __init__(self, fullscreen=True, speak=True, size=(1280, 720), progress_file=None,
                 seed=None, sound=True):
        self.rng = random.Random(seed)
        pygame.init()
        self.chime = None
        if sound:
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
                self.chime = make_chime()
                self.chime.set_volume(0.5)
            except pygame.error:
                pass  # no audio device: play silently

        self.progress = Progress(progress_file or progress_path())
        self.languages = available_languages()
        language = self.progress.language if self.progress.language in self.languages else BASE_LANGUAGE
        self.strings = Strings.load(rng=self.rng, language=language)
        pygame.display.set_caption(self.strings.ui("window_title"))
        if fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(size)
        self.W, self.H = self.screen.get_size()
        self.clock = pygame.time.Clock()
        h = self.H
        self.font_title = gfx.font(h * 0.125)
        self.font_big = gfx.font(h * 0.060)
        self.font_mid = gfx.font(h * 0.044)
        self.font_small = gfx.font(h * 0.032)
        self.font_note = gfx.font(h * 0.028, "bold")

        self.screen.blit(gfx.vertical_gradient((self.W, self.H), OCEAN_TOP, OCEAN_BOTTOM), (0, 0))
        loading = self.font_big.render(self.strings.ui("loading"), True, WHITE)
        self.screen.blit(loading, loading.get_rect(center=(self.W // 2, self.H // 2)))
        pygame.display.flip()

        self.world = WorldMap.load()
        self.tasks, self.task_problems = load_tasks(self.world)
        for problem in self.task_problems:
            print("tasks.json:", problem)
        self.speaker = Speaker(self.strings.language, enabled=speak)

        self.bar_h = int(self.H * 0.15)
        self.viewport = Viewport(0, self.bar_h, self.W, self.H - self.bar_h)
        self.renderer = MapRenderer(self.world, self.viewport)

        self.state = MENU
        self.running = True
        self.level = 1
        self.round = None
        self.phase = "asking"          # or "celebrate"
        self.phase_started = 0.0
        self.flash_areas = []
        self.banner_text = ""
        self.banner_until = 0.0
        self.message = ""
        self.particles = []
        self.miss_marks = []           # (lon, lat, time) of recent wrong clicks
        self.hover_area = None
        self._hover_key = None
        self.mouse_down_pos = None
        self.dragging = False
        self.last_mouse = (0, 0)
        self._text_cache = {}
        self._backdrop = None
        self._bar_shadow = None
        self._picture_start = 0.0
        self.end_started = 0.0
        self.frame = 0

        self._build_buttons()
        self.speaker.say(self.strings.speech("welcome"))

    # ------------------------------------------------------------------ setup
    def _build_buttons(self):
        W, H, s = self.W, self.H, self.strings
        # Start screen: three big level cards and Quit.
        bw, bh = int(W * 0.25), int(H * 0.38)
        gap = int(W * 0.035)
        x0 = (W - (3 * bw + 2 * gap)) // 2
        y0 = int(H * 0.40)
        self.level_buttons = [
            Button(("level", i + 1), (x0 + i * (bw + gap), y0, bw, bh), "", LEVEL_COLORS[i])
            for i in range(3)
        ]
        # Language flags, bottom left of the start screen.
        fh = int(H * 0.085)
        fw = int(fh * 1.5)
        self.language_buttons = [
            Button(("lang", code), (int(W * 0.03) + i * (fw + int(H * 0.035)), H - fh - int(H * 0.045), fw, fh),
                   "" if gfx.flag(code, fh) else code.upper(), SOFT)
            for i, code in enumerate(self.languages)
        ] if len(self.languages) > 1 else []
        qw, qh = int(W * 0.13), int(H * 0.08)
        self.quit_button = Button("quit", (W - qw - int(W * 0.025), H - qh - int(H * 0.04), qw, qh),
                                  s.ui("quit"), SOFT)

        # Play screen: Menu on the left of the bar, Whole map and Repeat on the right.
        pad = int(self.bar_h * 0.20)
        bh2 = self.bar_h - 2 * pad
        self.home_button = Button("home", (pad, pad, int(bh2 * 2.1), bh2), s.ui("home"),
                                  SOFT, icon="home")
        rw = int(bh2 * 2.7)
        self.repeat_button = Button("repeat", (W - pad - rw, pad, rw, bh2), s.ui("repeat"),
                                    ORANGE, icon="speaker")
        vw = int(bh2 * 3.1)
        self.reset_button = Button("reset", (self.repeat_button.rect.left - pad - vw, pad, vw, bh2),
                                   s.ui("reset_view"), BLUE, icon="globe")
        self._fit_button_labels([self.home_button, self.repeat_button, self.reset_button])
        zs = int(H * 0.075)
        zx = W - zs - int(W * 0.014)
        zy = self.bar_h + int(H * 0.03)
        self.zoom_in_button = Button("zoom_in", (zx, zy, zs, zs), "", SOFT, icon="plus")
        self.zoom_out_button = Button("zoom_out", (zx, zy + zs + int(H * 0.018), zs, zs), "",
                                      SOFT, icon="minus")
        self.play_buttons = [self.home_button, self.reset_button, self.repeat_button,
                             self.zoom_in_button, self.zoom_out_button]
        self.text_left = self.home_button.rect.right + pad
        self.text_right = self.reset_button.rect.left - pad

        # End screen.
        ew, eh = int(W * 0.24), int(H * 0.115)
        ey = int(H * 0.70)
        self.again_button = Button("again", (W // 2 - ew - gap // 2, ey, ew, eh), s.ui("play_again"), GREEN)
        self.change_button = Button("change", (W // 2 + gap // 2, ey, ew, eh), s.ui("change_level"), BLUE)
        for b, side in ((self.again_button, "left"), (self.change_button, "right")):
            needed = self.font_mid.size(b.label)[0] + int(eh * 1.1)  # translated labels can be long
            if needed > b.rect.width:
                if side == "left":
                    b.rect.x -= needed - b.rect.width
                b.rect.width = needed
        self.end_buttons = [self.again_button, self.change_button, self.quit_button]

    def _fit_button_labels(self, buttons):
        """Widen buttons whose (possibly translated) label would not fit."""
        for b in buttons:
            needed = self.font_small.size(b.label)[0] + int(b.rect.height * 1.5)
            if needed > b.rect.width:
                grow = needed - b.rect.width
                if b.rect.centerx > self.W // 2:
                    b.rect.x -= grow
                b.rect.width = needed
        # Keep the two right-hand buttons from overlapping after growing.
        pad = int(self.bar_h * 0.20)
        self.reset_button.rect.right = self.repeat_button.rect.left - pad

    def set_language(self, code):
        """Switch the whole game (texts, prompts and voice) to another language."""
        if code == self.strings.language or code not in self.languages:
            return
        self.strings = Strings.load(rng=self.rng, language=code)
        self.speaker.set_language(code)
        self.progress.language = code
        self.progress.save()
        self._text_cache.clear()
        pygame.display.set_caption(self.strings.ui("window_title"))
        self._build_buttons()
        self.speaker.say(self.strings.speech("welcome"))

    def prompt(self):
        """The current task's prompt in the chosen language."""
        return self.strings.prompt(self.round.task)

    # ------------------------------------------------------------- game flow
    def start_round(self, level, tasks=None):
        self.level = level
        chosen = tasks or select_round(self.tasks, level, self.progress, self.rng)
        if not chosen:
            self.message = self.strings.ui("no_tasks")
            return
        self.message = ""
        self.round = Round(self.world, chosen, self.progress, level, rng=self.rng)
        self.state = PLAY
        self.particles.clear()
        self.begin_task()

    def begin_task(self):
        self.phase = "asking"
        self.phase_started = time.monotonic()
        self.flash_areas = []
        self.miss_marks.clear()
        self.banner_text = ""
        self.viewport.reset()
        self._hover_key = None
        self._picture_start = time.monotonic()
        self.speaker.say(self.prompt())

    def go_menu(self):
        self.state = MENU
        self.round = None
        self.particles.clear()
        self.speaker.stop()

    def end_round(self):
        self.state = END
        self.end_started = time.monotonic()
        self.speaker.say(round_end_text(self.strings, self.round.stars, len(self.round.tasks)))
        if self.chime:
            self.chime.play()
        for _ in range(4):
            self._confetti(self.rng.randint(int(self.W * 0.2), int(self.W * 0.8)),
                           self.rng.randint(int(self.H * 0.2), int(self.H * 0.5)), 50)

    def on_map_click(self, pos):
        if self.phase != "asking" or self.round is None:
            return
        lon, lat = self.viewport.to_world(*pos)
        outcome = self.round.click(lon, lat, self.viewport.scale)
        if outcome is None:
            return
        s = self.strings
        if outcome.kind == "correct":
            self.phase = "celebrate"
            self.phase_started = time.monotonic()
            self.flash_areas = list(self.round.task.areas)
            text = s.speech("praise") if outcome.star else s.speech("after_hint")
            self.speaker.say(text)
            self._banner(text)
            self._confetti(pos[0], pos[1], 90)
            if self.chime:
                self.chime.play()
            return
        # Each sentence is its own pre-recorded clip, so they are spoken one
        # after the other in the order the pattern puts them on screen.
        that_is = s.speech("that_is", name=s.area_name(outcome.clicked))
        if outcome.hint_started:
            hint = s.speech("hint")
            text = s.speech("hint_pattern", that_is=that_is, hint=hint)
            parts = [that_is, hint]
            self.viewport.reset()  # make sure the glowing answer is on screen
        elif self.round.hint_active:
            text = that_is
            parts = [that_is]
        elif outcome.zone_started:
            clue = s.speech("zone")
            text = s.speech("zone_pattern", that_is=that_is, zone=clue)
            parts = [that_is, clue]
            if not self._zone_visible():
                self.viewport.reset()  # make sure the whole box is on screen
        else:
            phrase = s.speech("close" if outcome.kind == "close" else "wrong")
            text = s.speech("wrong_pattern", phrase=phrase, that_is=that_is)
            parts = [phrase, that_is]
        parts.sort(key=text.find)
        self.miss_marks.append((lon, lat, time.monotonic()))
        self.speaker.say(parts)
        self._banner(text)

    def _zone_visible(self):
        zone = self.round.zone if self.round else None
        if zone is None:
            return True
        view = self.viewport.visible_box()
        return view[0] <= zone[0] and view[1] <= zone[1] and view[2] >= zone[2] and view[3] >= zone[3]

    # ---- the picture that goes with animal and landmark questions ----
    def _picture_id(self):
        task = self.round.task if self.round else None
        if task is None or not task.picture or gfx.picture_path(task.picture) is None:
            return ""
        return task.picture

    def _thumb_rect(self):
        height = int(self.bar_h * 0.84)
        width = int(height * gfx.picture_aspect(self._picture_id()))
        return pygame.Rect(self.text_left, (self.bar_h - height) // 2, width, height)

    @property
    def picture_intro_active(self):
        """True while the big picture covers the map at the start of a task."""
        return (self.state == PLAY and self.phase == "asking" and bool(self._picture_id())
                and time.monotonic() - self._picture_start < PICTURE_SECONDS)

    def _picture_rect(self):
        """Where the picture is right now: big over the map, shrinking, or a
        thumbnail next to the question. Hovering the thumbnail enlarges it."""
        thumb = self._thumb_rect()
        aspect = gfx.picture_aspect(self._picture_id())
        height = int(self.H * (0.52 if aspect >= 1 else 0.62))  # tall pictures get more height
        big = pygame.Rect(0, 0, int(height * aspect), height)
        big.center = (self.W // 2, self.bar_h + (self.H - self.bar_h) // 2 - int(self.H * 0.03))
        elapsed = time.monotonic() - self._picture_start
        if self.phase != "asking":
            return thumb
        if elapsed >= PICTURE_SECONDS:
            return big if thumb.collidepoint(self.last_mouse) else thumb
        t = (elapsed - (PICTURE_SECONDS - PICTURE_SHRINK_SECONDS)) / PICTURE_SHRINK_SECONDS
        if t <= 0:
            return big
        t = t * t * (3 - 2 * t)  # ease in and out
        return pygame.Rect(round(big.x + (thumb.x - big.x) * t), round(big.y + (thumb.y - big.y) * t),
                           round(big.w + (thumb.w - big.w) * t), round(big.h + (thumb.h - big.h) * t))

    def _draw_picture(self):
        picture_id = self._picture_id()
        if not picture_id:
            return
        rect = self._picture_rect()
        image = gfx.picture(picture_id, rect.width, rect.height)
        if image is None:
            return
        border = max(3, rect.height // 40)
        frame = rect.inflate(border * 2, border * 2)
        gfx.draw_panel(self.screen, frame, WHITE, int(min(frame.size) * 0.19),
                       shadow=max(4, min(rect.height // 14, self.H // 60)))
        self.screen.blit(image, rect)

    def _draw_pin(self, now):
        """Marks the exact spot of a landmark once it is found or shown."""
        task = self.round.task
        if task is None or task.pin is None:
            return
        x, y = self.viewport.to_screen(*task.pin)
        if not self.viewport.contains_screen_point(x, y):
            return
        image = gfx.pin(int(self.H * 0.05))
        bob = abs(math.sin(now * 4.0)) * self.H * 0.012
        self.screen.blit(image, (int(x - image.get_width() / 2), int(y - image.get_height() - bob)))

    def _banner(self, text):
        self.banner_text = text
        self.banner_until = time.monotonic() + BANNER_SECONDS

    def _confetti(self, x, y, count):
        for _ in range(count):
            angle = self.rng.uniform(0, 2 * math.pi)
            speed = self.rng.uniform(150, 650) * self.H / 1080
            self.particles.append([x, y, math.cos(angle) * speed, math.sin(angle) * speed - 250,
                                   self.rng.choice(CONFETTI), self.rng.uniform(1.0, 2.0),
                                   self.rng.randint(5, 10) * self.H / 1080 + 2,
                                   self.rng.random() < 0.5])

    # ------------------------------------------------------------------ input
    def _buttons(self):
        if self.state == MENU:
            return self.level_buttons + self.language_buttons + [self.quit_button]
        if self.state == PLAY:
            return self.play_buttons
        return self.end_buttons

    def _button_at(self, pos):
        for b in self._buttons():
            if b.rect.collidepoint(pos):
                return b
        return None

    def press(self, key):
        """Run a button action (also used by the automated smoke test)."""
        if key == "quit":
            self.running = False
        elif isinstance(key, tuple) and key[0] == "level":
            self.start_round(key[1])
        elif isinstance(key, tuple) and key[0] == "lang":
            self.set_language(key[1])
        elif key == "home" or key == "change":
            self.go_menu()
        elif key == "again":
            self.start_round(self.level)
        elif key == "repeat":
            if self.round and self.round.task:
                self.speaker.say(self.prompt())
        elif key == "reset":
            self.viewport.reset()
        elif key == "zoom_in":
            self.viewport.zoom_at(self.viewport.x + self.viewport.width / 2,
                                  self.viewport.y + self.viewport.height / 2, ZOOM_STEP ** 2)
        elif key == "zoom_out":
            self.viewport.zoom_at(self.viewport.x + self.viewport.width / 2,
                                  self.viewport.y + self.viewport.height / 2, 1 / ZOOM_STEP ** 2)

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.running = False
        elif event.type == pygame.MOUSEMOTION:
            self.last_mouse = event.pos
            if self.mouse_down_pos is not None and self.state == PLAY:
                if not self.dragging:
                    dx = event.pos[0] - self.mouse_down_pos[0]
                    dy = event.pos[1] - self.mouse_down_pos[1]
                    if dx * dx + dy * dy > DRAG_THRESHOLD_PX ** 2:
                        self.dragging = True
                        self.viewport.pan(dx, dy)
                else:
                    self.viewport.pan(*event.rel)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.last_mouse = event.pos
            button = self._button_at(event.pos)
            if button is not None:
                self.press(button.key)
            elif self.picture_intro_active:
                # A click while the big picture is up just puts it away.
                elapsed = time.monotonic() - self._picture_start
                if elapsed < PICTURE_SECONDS - PICTURE_SHRINK_SECONDS:
                    self._picture_start -= PICTURE_SECONDS - PICTURE_SHRINK_SECONDS - elapsed
            elif self.state == PLAY and self._picture_id() and self._thumb_rect().collidepoint(event.pos):
                self._picture_start = time.monotonic()  # clicking the thumbnail shows it big again
            elif self.state == PLAY and self.viewport.contains_screen_point(*event.pos):
                self.mouse_down_pos = event.pos
                self.dragging = False
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.mouse_down_pos is not None:
                was_drag = self.dragging
                self.mouse_down_pos = None
                self.dragging = False
                if not was_drag and self.state == PLAY:
                    self.on_map_click(event.pos)
        elif event.type == pygame.MOUSEWHEEL and self.state == PLAY:
            pos = self.last_mouse
            if self.viewport.contains_screen_point(*pos) and event.y:
                self.viewport.zoom_at(pos[0], pos[1], ZOOM_STEP ** event.y)

    # ----------------------------------------------------------------- update
    def update(self, dt):
        now = time.monotonic()
        self.speaker.update()
        if self.state == PLAY and self.phase == "celebrate":
            elapsed = now - self.phase_started
            if elapsed >= CELEBRATION_MIN_SECONDS and (not self.speaker.busy or elapsed >= CELEBRATION_MAX_SECONDS):
                if self.round.advance():
                    self.begin_task()
                else:
                    self.end_round()
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 900 * dt * self.H / 1080
            p[5] -= dt
        self.particles = [p for p in self.particles if p[5] > 0 and p[1] < self.H + 20]
        self._update_hover()

    def _update_hover(self):
        if self.state != PLAY or self.dragging or self.phase != "asking":
            self.hover_area = None
            self._hover_key = None
            return
        pos = self.last_mouse
        key = (pos, self.viewport.version)
        if key == self._hover_key:
            return
        self._hover_key = key
        if (not self.viewport.contains_screen_point(*pos) or self._button_at(pos)
                or self.picture_intro_active):
            self.hover_area = None
            return
        self.hover_area = self.world.country_at(*self.viewport.to_world(*pos))

    # ------------------------------------------------------------------- draw
    def _fit_text(self, text, max_width, max_height, color=INK, start=0.075):
        """Render text as large as fits, on one or two lines. Cached."""
        key = (text, max_width, max_height, color, start)
        if key in self._text_cache:
            return self._text_cache[key]
        size = int(self.H * start)
        result = None
        while size >= 14:
            font = gfx.font(size)
            lines = [text]
            if font.size(text)[0] > max_width:
                words = text.split()
                best = None
                for i in range(1, len(words)):
                    a, b = " ".join(words[:i]), " ".join(words[i:])
                    width = max(font.size(a)[0], font.size(b)[0])
                    if best is None or width < best[0]:
                        best = (width, [a, b])
                if best:
                    lines = best[1]
            width = max(font.size(l)[0] for l in lines)
            height = font.get_linesize() * len(lines)
            if width <= max_width and height <= max_height:
                result = [font.render(l, True, color) for l in lines]
                break
            size -= 3
        if result is None:
            result = [self.font_note.render(text, True, color)]
        if len(self._text_cache) > 200:
            self._text_cache.clear()
        self._text_cache[key] = result
        return result

    def _blit_lines(self, surfaces, center):
        total = sum(s.get_height() for s in surfaces)
        y = center[1] - total // 2
        for s in surfaces:
            self.screen.blit(s, (center[0] - s.get_width() // 2, y))
            y += s.get_height()

    def _draw_buttons(self, buttons, font):
        mouse = self.last_mouse
        for b in buttons:
            b.draw(self.screen, font, b.rect.collidepoint(mouse))

    def draw(self):
        if self.state == MENU:
            self._draw_menu()
        elif self.state == PLAY:
            self._draw_play()
        else:
            self._draw_end()
        for x, y, vx, _, color, life, size, round_piece in self.particles:
            if round_piece:
                pygame.draw.circle(self.screen, color, (int(x), int(y)), int(size * 0.55))
            else:
                # A flat rectangle that appears to tumble as it falls.
                squash = abs(math.sin(life * 9 + vx))
                rect = pygame.Rect(0, 0, int(size * 1.3), max(2, int(size * 0.9 * squash)))
                rect.center = (int(x), int(y))
                pygame.draw.rect(self.screen, color, rect, border_radius=2)
        pygame.display.flip()

    def _draw_backdrop(self):
        """The map, blurred and washed out, behind the menu and end screens."""
        if self._backdrop is None:
            self.viewport.reset()
            base = pygame.Surface((self.W, self.H)).convert()
            base.blit(gfx.vertical_gradient((self.W, self.H), OCEAN_TOP, OCEAN_BOTTOM), (0, 0))
            self.renderer.draw(base, smooth_now=True)
            base = pygame.transform.gaussian_blur(base, max(2, self.H // 180))
            veil = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            veil.fill((255, 255, 255, 105))
            base.blit(veil, (0, 0))
            self._backdrop = base
        self.screen.blit(self._backdrop, (0, 0))

    def _draw_title(self, text, y):
        title = self.font_title.render(text, True, INK)
        self.screen.blit(title, title.get_rect(center=(self.W // 2, y)))

    def _draw_menu(self):
        s = self.strings
        self._draw_backdrop()
        self._draw_title(s.ui("title"), int(self.H * 0.15))
        sub = self.font_mid.render(self.message or s.ui("subtitle"), True, INK_SOFT)
        self.screen.blit(sub, sub.get_rect(center=(self.W // 2, int(self.H * 0.285))))
        mouse = self.last_mouse
        for i, b in enumerate(self.level_buttons):
            hovered = b.rect.collidepoint(mouse)
            r = b.rect.move(0, -int(self.H * 0.008)) if hovered else b.rect
            color = gfx.lighten(b.color, 0.10) if hovered else b.color
            gfx.draw_panel(self.screen, r, color, int(self.H * 0.045),
                           shadow=int(self.H * 0.022), gradient=0.20)
            level = i + 1
            radius = int(r.height * 0.105)
            for k in range(level):
                cx = r.centerx + int((k - (level - 1) / 2) * radius * 2.5)
                gfx.draw_star(self.screen, cx, r.top + int(r.height * 0.23), radius, WHITE)
            label = self.font_big.render(s.ui(f"level_{level}"), True, WHITE)
            self.screen.blit(label, label.get_rect(center=(r.centerx, r.top + int(r.height * 0.50))))
            hint = self._fit_text(s.ui(f"level_{level}_hint"), r.width - int(r.width * 0.16),
                                  int(r.height * 0.24), WHITE, start=0.034)
            self._blit_lines(hint, (r.centerx, r.top + int(r.height * 0.72)))
            best = self.progress.best_for(level)
            if best:
                text = self.font_note.render(s.ui("best_score", stars=best, total=ROUND_LENGTH), True, WHITE)
                pill = text.get_rect(center=(r.centerx, r.bottom - int(r.height * 0.085))).inflate(
                    int(self.H * 0.03), int(self.H * 0.008))
                gfx.draw_panel(self.screen, pill, gfx.darken(b.color, 0.16), pill.height // 2, shadow=0)
                self.screen.blit(text, text.get_rect(center=pill.center))
        self.quit_button.draw(self.screen, self.font_small, self.quit_button.rect.collidepoint(mouse))
        self._draw_collection()
        for b in self.language_buttons:
            code = b.key[1]
            chosen = code == self.strings.language
            hovered = b.rect.collidepoint(mouse)
            r = b.rect.move(0, -2) if hovered and not chosen else b.rect
            image = gfx.flag(code, r.height)
            if image is None:
                b.draw(self.screen, self.font_small, hovered)
            else:
                gfx.draw_panel(self.screen, r, WHITE, int(r.height * 0.16), shadow=max(4, r.height // 8))
                if not chosen:
                    image = image.copy()
                    image.set_alpha(150)  # the flag not in use is faded
                self.screen.blit(image, r)
            if chosen:
                ring = r.inflate(int(r.height * 0.22), int(r.height * 0.22))
                pygame.draw.rect(self.screen, BLUE, ring, max(3, r.height // 14),
                                 border_radius=int(ring.height * 0.22))

    def _draw_play(self):
        screen = self.screen
        now = time.monotonic()
        rnd = self.round
        self.renderer.draw(screen)

        if self.hover_area is not None:
            self.renderer.draw_hover(screen, self.hover_area)

        pulse = 0.5 + 0.5 * math.sin(now * 7.0)
        if self.phase == "celebrate":
            self.renderer.draw_highlight(screen, self.flash_areas,
                                         (46, 204, 130, int(120 + 110 * pulse)), (20, 160, 95), 3)
            self._draw_rings(self.flash_areas, (30, 180, 110), pulse)
            self._draw_pin(now)
        elif rnd.hint_active:
            self.renderer.draw_highlight(screen, rnd.task.areas,
                                         (255, 205, 40, int(70 + 110 * pulse)),
                                         (255, int(140 + 60 * pulse), 20), int(3 + 3 * pulse))
            self._draw_rings(rnd.task.areas, (255, 130, 20), pulse)
            self._draw_pin(now)
        elif rnd.zone is not None:
            self._draw_zone(rnd.zone, now)

        # Soft markers where wrong clicks landed.
        for lon, lat, t in self.miss_marks:
            age = now - t
            if age < 2.5:
                x, y = self.viewport.to_screen(lon, lat)
                if self.viewport.contains_screen_point(x, y):
                    r = int(self.H * 0.012 + age * self.H * 0.01)
                    pygame.draw.aacircle(screen, WHITE, (int(x), int(y)), r + 2, 4)
                    pygame.draw.aacircle(screen, (255, 130, 110), (int(x), int(y)), r, 3)

        # Top bar with the task text.
        if self._bar_shadow is None:
            strip = pygame.Surface((1, 14), pygame.SRCALPHA)
            for y in range(14):
                strip.set_at((0, y), (20, 50, 100, int(46 * (1 - y / 14) ** 2)))
            self._bar_shadow = pygame.transform.smoothscale(strip, (self.W, 14))
        screen.blit(self._bar_shadow, (0, self.bar_h))
        pygame.draw.rect(screen, WHITE, (0, 0, self.W, self.bar_h))
        text_left = self.text_left
        if self._picture_id():  # leave room for the thumbnail
            text_left = self._thumb_rect().right + int(self.bar_h * 0.15)
        lines = self._fit_text(self.prompt(), self.text_right - text_left, self.bar_h - 12)
        self._blit_lines(lines, ((text_left + self.text_right) // 2, self.bar_h // 2))
        self._draw_buttons(self.play_buttons, self.font_small)

        self._draw_star_row()
        if self.banner_text and now < self.banner_until:
            self._draw_banner(self.banner_text)
        self._draw_picture()

    def _draw_zone(self, zone, now):
        """The "look in here" box: a frame with four arrows pointing at its edges."""
        screen = self.screen
        vp = self.viewport
        x0, y1 = vp.to_screen(zone[0], zone[1])
        x1, y0 = vp.to_screen(zone[2], zone[3])
        rect = pygame.Rect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
        view = pygame.Rect(vp.x, vp.y, vp.width, vp.height)
        old_clip = screen.get_clip()
        screen.set_clip(view)
        # Everything outside the box is dimmed a little.
        shade = pygame.Surface(view.size, pygame.SRCALPHA)
        shade.fill((30, 50, 90, 70))
        shade.fill((0, 0, 0, 0), rect.move(-view.x, -view.y))
        screen.blit(shade, view)
        radius = max(6, self.H // 60)
        pygame.draw.rect(screen, WHITE, rect.inflate(8, 8), 9, border_radius=radius + 4)
        pygame.draw.rect(screen, ORANGE, rect.inflate(2, 2), 4, border_radius=radius)
        size = int(self.H * 0.075)
        bob = int((0.5 + 0.5 * math.sin(now * 5.0)) * self.H * 0.014)
        gap = int(self.H * 0.012) + bob
        # Each arrow sits outside its edge and points at it; if the edge is at
        # the border of the map, the arrow moves inside so it is still seen.
        spots = [
            ("right", (rect.left - gap - size, rect.centery - size // 2), (rect.left + gap, rect.centery - size // 2), "left"),
            ("left", (rect.right + gap, rect.centery - size // 2), (rect.right - gap - size, rect.centery - size // 2), "right"),
            ("down", (rect.centerx - size // 2, rect.top - gap - size), (rect.centerx - size // 2, rect.top + gap), "up"),
            ("up", (rect.centerx - size // 2, rect.bottom + gap), (rect.centerx - size // 2, rect.bottom - gap - size), "down"),
        ]
        for direction, outside, inside, flipped in spots:
            box = pygame.Rect(outside, (size, size))
            if view.contains(box):
                screen.blit(gfx.arrow(size, ORANGE, direction), outside)
            else:
                screen.blit(gfx.arrow(size, ORANGE, flipped), inside)
        screen.set_clip(old_clip)

    def _draw_collection(self):
        """Counters of what has been found so far: Countries 12/40, Animals 3/22 ..."""
        groups = collection(self.tasks, self.progress)
        if not groups:
            return
        left = int(self.W * 0.235)
        right = self.quit_button.rect.left - int(self.W * 0.02)
        height = int(self.H * 0.105)
        rect = pygame.Rect(left, self.H - height - int(self.H * 0.035), right - left, height)
        gfx.draw_panel(self.screen, rect, WHITE, int(self.H * 0.03), shadow=max(4, self.H // 110))
        cell = rect.width / len(groups)
        for i, (name, found, total) in enumerate(groups):
            cx = int(rect.left + cell * (i + 0.5))
            done = found >= total
            label = self._fit_text(self.strings.ui(f"category_{name}"), int(cell * 0.9),
                                   int(rect.height * 0.34), INK_SOFT, start=0.026)
            self._blit_lines(label[:1], (cx, rect.top + int(rect.height * 0.25)))
            count = self.font_note.render(f"{found}/{total}", True, INK)
            bar_w = int(cell * 0.5)
            total_w = bar_w + int(self.H * 0.012) + count.get_width()
            x = cx - total_w // 2
            y = rect.top + int(rect.height * 0.66)
            bar = pygame.Rect(x, y - int(self.H * 0.007), bar_w, max(6, int(self.H * 0.014)))
            pygame.draw.rect(self.screen, EMPTY, bar, border_radius=bar.height // 2)
            if found:
                fill = bar.copy()
                fill.width = max(bar.height, int(bar.width * found / total))
                pygame.draw.rect(self.screen, GOLD if done else GREEN, fill, border_radius=bar.height // 2)
            self.screen.blit(count, (bar.right + int(self.H * 0.012), y - count.get_height() // 2))

    def _draw_rings(self, areas, color, pulse):
        """Circle small targets so a tiny island is impossible to miss."""
        vp = self.viewport
        limit = int(self.H * 0.045)
        drawn = 0
        for area in areas:
            box = self.renderer.main_screen_box(area)  # mainland, not far-off islands
            if box.width > limit or box.height > limit:
                continue
            if not vp.contains_screen_point(*box.center):
                continue
            radius = int(max(box.width, box.height) / 2 + self.H * 0.03 + self.H * 0.012 * pulse)
            pygame.draw.aacircle(self.screen, WHITE, box.center, radius + 3, 9)
            pygame.draw.aacircle(self.screen, color, box.center, radius, 5)
            drawn += 1
            if drawn >= 12:
                break

    def _draw_star_row(self):
        rnd = self.round
        n = len(rnd.tasks)
        radius = int(self.H * 0.021)
        step = int(radius * 2.6)
        counter = self.font_note.render(
            self.strings.ui("task_counter", number=min(rnd.index + 1, n), total=n), True, INK_SOFT)
        width = n * step + counter.get_width() + radius * 3
        rect = pygame.Rect(0, 0, width, int(radius * 3.3))
        rect.midbottom = (self.W // 2, self.H - int(self.H * 0.022))
        gfx.draw_panel(self.screen, rect, WHITE, rect.height // 2, shadow=max(4, self.H // 130))
        x = rect.left + int(radius * 1.9)
        for i in range(n):
            result = rnd.results[i]
            if result:
                gfx.draw_star(self.screen, x, rect.centery, radius)
            elif result is False:
                pygame.draw.aacircle(self.screen, HELPED, (x, rect.centery), int(radius * 0.5))
            else:
                gfx.draw_star(self.screen, x, rect.centery, radius * 0.82, EMPTY)
            if i == rnd.index and rnd.results[i] is None:
                pygame.draw.aacircle(self.screen, BLUE, (x, rect.centery), int(radius * 1.3), 3)
            x += step
        self.screen.blit(counter, (x - radius // 3, rect.centery - counter.get_height() // 2))

    def _draw_banner(self, text):
        lines = self._fit_text(text, int(self.W * 0.7), int(self.H * 0.07), INK, start=0.045)
        width = max(l.get_width() for l in lines) + int(self.H * 0.07)
        height = sum(l.get_height() for l in lines) + int(self.H * 0.022)
        rect = pygame.Rect(0, 0, width, height)
        rect.midbottom = (self.W // 2, self.H - int(self.H * 0.115))
        gfx.draw_panel(self.screen, rect, WHITE, rect.height // 2, shadow=max(5, self.H // 110))
        self._blit_lines(lines, rect.center)

    def _draw_end(self):
        s = self.strings
        rnd = self.round
        self._draw_backdrop()
        self._draw_title(s.ui("round_over_title"), int(self.H * 0.16))
        total = len(rnd.tasks)
        elapsed = time.monotonic() - self.end_started
        radius = min(int(self.H * 0.062), int(self.W * 0.8 / max(1, total) / 2.5))
        step = int(radius * 2.5)
        card = pygame.Rect(0, 0, step * total + radius * 2, int(radius * 3.6))
        card.center = (self.W // 2, int(self.H * 0.40))
        gfx.draw_panel(self.screen, card, WHITE, card.height // 2, shadow=int(self.H * 0.016))
        x = self.W // 2 - step * (total - 1) // 2
        for i in range(total):
            appear = 0.25 + i * 0.18
            if i < rnd.stars and elapsed >= appear:
                t = min(1.0, (elapsed - appear) / 0.3)
                pop = 1.0 + 0.35 * math.sin(t * math.pi)  # grows past full size, settles back
                gfx.draw_star(self.screen, x, card.centery, radius * (0.3 + 0.7 * t) * pop,
                              angle=math.sin(elapsed * 3 + i) * 6)
            else:
                gfx.draw_star(self.screen, x, card.centery, radius * 0.85, EMPTY)
            x += step
        line = self.font_big.render(s.ui("score_line", stars=rnd.stars, total=total), True, INK)
        self.screen.blit(line, line.get_rect(center=(self.W // 2, int(self.H * 0.57))))
        self._draw_buttons([self.again_button, self.change_button], self.font_mid)
        self._draw_collection()
        self.quit_button.draw(self.screen, self.font_small, self.quit_button.rect.collidepoint(self.last_mouse))

    # ------------------------------------------------------------------- loop
    def run(self, driver=None):
        """Main loop. ``driver(app)`` is called once per frame if given; the
        smoke test uses it to post mouse events like a player would."""
        try:
            while self.running:
                dt = min(0.05, self.clock.tick(FPS) / 1000.0)
                self.frame += 1
                if driver is not None:
                    driver(self)
                for event in pygame.event.get():
                    self.handle_event(event)
                self.update(dt)
                self.draw()
        finally:
            self.progress.save()
            self.speaker.shutdown()
            pygame.quit()
