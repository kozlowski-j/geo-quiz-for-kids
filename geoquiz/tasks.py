"""Task engine: loading tasks, saved progress, picking a round, judging clicks.

No pygame here, so everything can be unit-tested without a window.
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from .paths import resource_path

TASKS_FILE = "data/tasks.json"
ANIMALS_FILE = "data/animals.json"

TASK_TYPES = ("country", "feature", "animal", "landmark")
ROUND_LENGTH = 10
SAVE_VERSION = 1            # written to progress.json, for future migrations
MAX_REVIEW_TASKS = 5        # at most this many "got it wrong last time" tasks per round
MAX_WRONG_ATTEMPTS = 3      # then the answer is shown
ZONE_AFTER_WRONG = 2        # after this many misses a box shows where to look

# The collection shown on the start screen: every task belongs to one group.
CATEGORIES = ("countries", "continents", "water", "mountains", "places", "landmarks", "animals")
WORLD_BOX = (-180.0, -90.0, 180.0, 84.0)

CLICK_TOLERANCE_PX = 15     # a click this near a target still counts
BORDER_SLOP_PX = 1          # ...but only this near if it landed in another country
SMALL_TARGET_PX = 30        # targets smaller than this on screen always get the full tolerance

# A level-1 country must be at least this big (side of an equal-area square,
# in degrees). On a full-HD screen the whole-world view shows about 5.3
# pixels per degree, so 3 degrees is roughly a 16 pixel blob.
EASY_MIN_SIZE_DEG = 3.0


@dataclass
class Task:
    id: str
    type: str
    prompt: str
    targets: list            # references as written in the file
    difficulty: int
    areas: list = field(default_factory=list)  # resolved map areas
    picture: str = ""        # id of a picture in data/pictures (animals and landmarks)
    pin: tuple | None = None  # (lon, lat) of the exact spot, shown once it is found


def task_category(task):
    """Which collection group a task counts towards."""
    if task.type == "country":
        return "countries"
    if task.type == "animal":
        return "animals"
    if task.type == "landmark":
        return "landmarks"
    area = task.areas[0] if task.areas else None
    kind = getattr(area, "kind", "")
    if kind == "continent":
        return "continents"
    if kind in ("ocean", "sea", "river", "lake"):
        return "water"
    if kind == "region" and getattr(area, "cls", "") == "Range/mtn":
        return "mountains"
    return "places"  # deserts, islands, rainforests, regions


def collection(tasks, progress):
    """[(category, found, total)] for every category that has tasks."""
    totals = {c: [0, 0] for c in CATEGORIES}
    for task in tasks:
        entry = totals[task_category(task)]
        entry[1] += 1
        if progress is not None and progress.found(task.id):
            entry[0] += 1
    return [(c, found, total) for c, (found, total) in totals.items() if total]


def search_zone(areas, rng=None):
    """A box (lon0, lat0, lon1, lat1) that says "look in here".

    It surrounds the biggest piece of the biggest target with generous
    padding and is pushed off-centre at random, so it narrows the search
    without pointing straight at the answer.
    """
    rng = rng or random.Random()
    anchor = max(areas, key=lambda a: a.size_deg)
    x0, y0, x1, y1 = anchor.main_box
    pad_x = max((x1 - x0) * 0.5, 10.0)
    pad_y = max((y1 - y0) * 0.5, 8.0)
    shift_x = rng.uniform(-0.6, 0.6) * pad_x
    shift_y = rng.uniform(-0.6, 0.6) * pad_y
    return (max(WORLD_BOX[0], x0 - pad_x + shift_x), max(WORLD_BOX[1], y0 - pad_y + shift_y),
            min(WORLD_BOX[2], x1 + pad_x + shift_x), min(WORLD_BOX[3], y1 + pad_y + shift_y))


def load_animals(world, path=None):
    """Returns ({animal: [Area, ...]}, [problem strings])."""
    path = Path(path) if path else resource_path(ANIMALS_FILE)
    problems = []
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh).get("animals", {})
    animals = {}
    for key, entry in raw.items():
        areas = []
        for ref in entry.get("areas", []):
            area = world.find(ref)
            if area is None:
                problems.append(f"animal {key!r}: unknown area {ref!r}")
            elif area not in areas:
                areas.append(area)
        animals[key.lower()] = areas
    return animals, problems


def load_tasks(world, tasks_path=None, animals_path=None):
    """Read and validate the task file.

    Returns (tasks, problems). A broken task is skipped and described in
    ``problems`` instead of crashing the game, so a typo made while editing
    tasks.json costs one task, not the whole evening.
    """
    animals, problems = load_animals(world, animals_path)
    tasks_path = Path(tasks_path) if tasks_path else resource_path(TASKS_FILE)
    with open(tasks_path, encoding="utf-8") as fh:
        raw = json.load(fh).get("tasks", [])

    tasks = []
    seen = set()
    for number, entry in enumerate(raw, 1):
        task_id = str(entry.get("id") or f"task-{number}")
        label = f"task {task_id!r}"
        if task_id in seen:
            problems.append(f"{label}: duplicate id, skipped")
            continue
        task_type = entry.get("type")
        prompt = str(entry.get("prompt") or "").strip()
        difficulty = entry.get("difficulty")
        refs = entry.get("targets") or []
        if task_type not in TASK_TYPES:
            problems.append(f"{label}: type must be one of {TASK_TYPES}, skipped")
            continue
        if difficulty not in (1, 2, 3):
            problems.append(f"{label}: difficulty must be 1, 2 or 3, skipped")
            continue
        if not prompt:
            problems.append(f"{label}: empty prompt, skipped")
            continue

        areas = []
        for ref in refs:
            ref = str(ref).strip()
            if ref.lower().startswith("animal:"):
                found = animals.get(ref.split(":", 1)[1].strip().lower())
                if found is None:
                    problems.append(f"{label}: unknown animal {ref!r}")
                    continue
            else:
                area = world.find(ref)
                if area is None:
                    problems.append(f"{label}: unknown area {ref!r}")
                    continue
                found = [area]
            for area in found:
                if area not in areas:
                    areas.append(area)
        if not areas:
            problems.append(f"{label}: no valid targets, skipped")
            continue

        if difficulty == 1 and task_type == "country":
            countries = [a for a in areas if a.kind == "country"]
            if countries and max(a.size_deg for a in countries) < EASY_MIN_SIZE_DEG:
                problems.append(f"{label}: too small to click at level 1, skipped")
                continue

        picture = str(entry.get("picture") or "")
        if not picture:  # an animal question shows that animal
            for ref in refs:
                if str(ref).strip().lower().startswith("animal:"):
                    picture = str(ref).split(":", 1)[1].strip().lower()
                    break
        pin = entry.get("pin")
        if pin is not None:
            try:
                pin = (float(pin[0]), float(pin[1]))
                if len(entry["pin"]) != 2 or not (-180 <= pin[0] <= 180 and -90 <= pin[1] <= 90):
                    raise ValueError
            except (TypeError, ValueError, IndexError, KeyError):
                problems.append(f"{label}: pin must be [longitude, latitude], ignored")
                pin = None

        seen.add(task_id)
        tasks.append(Task(task_id, task_type, prompt, list(refs), difficulty, areas, picture, pin))
    return tasks, problems


class Progress:
    """What the child has seen and missed, kept in a small JSON file."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.tasks = {}   # task id -> {"seen": int, "missed": int, "last_missed": bool}
        self.best = {}    # level (as text) -> best star count
        self.language = ""  # language chosen on the start screen
        if self.path and self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
                tasks = data.get("tasks")
                best = data.get("best")
                if isinstance(tasks, dict):
                    self.tasks = {k: v for k, v in tasks.items() if isinstance(v, dict)}
                if isinstance(data.get("language"), str):
                    self.language = data["language"]
                if isinstance(best, dict):
                    self.best = {k: v for k, v in best.items() if isinstance(v, int)}
            except (OSError, ValueError, AttributeError, TypeError):
                pass  # unreadable save file: start fresh rather than crash

    def record(self, task_id, missed, found=None):
        """Note one finished task. ``found`` = solved before the answer had
        to be shown (defaults to "no wrong click at all")."""
        entry = self.tasks.setdefault(task_id, {"seen": 0, "missed": 0, "last_missed": False})
        entry["seen"] = int(entry.get("seen", 0)) + 1
        if missed:
            entry["missed"] = int(entry.get("missed", 0)) + 1
        entry["last_missed"] = bool(missed)
        if found is None:
            found = not missed
        if found:
            entry["found"] = True  # collected for good

    def found(self, task_id):
        """Has the child ever found this one unaided? Counts towards the collection."""
        entry = self.tasks.get(task_id)
        if not entry:
            return False
        if "found" in entry:
            return bool(entry["found"])
        # Save files from before the collection existed: a round without a
        # single wrong click on this task means it was found.
        return int(entry.get("seen", 0)) > int(entry.get("missed", 0))

    def record_round(self, level, stars):
        key = str(level)
        self.best[key] = max(int(self.best.get(key, 0)), int(stars))

    def best_for(self, level):
        return int(self.best.get(str(level), 0))

    def seen(self, task_id):
        return int(self.tasks.get(task_id, {}).get("seen", 0))

    def missed_last_time(self, task_id):
        return bool(self.tasks.get(task_id, {}).get("last_missed", False))

    def save(self):
        if not self.path:
            return
        try:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": SAVE_VERSION, "language": self.language,
                           "tasks": self.tasks, "best": self.best}, fh, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass  # read-only folder: the game still works, just forgets


def select_round(tasks, level, progress=None, rng=None, count=ROUND_LENGTH,
                 max_review=MAX_REVIEW_TASKS):
    """Pick the tasks for one round.

    * only tasks of the chosen level, never the same task twice;
    * up to ``max_review`` tasks the child got wrong the last time they came up;
    * the rest filled with the tasks seen least often, at random;
    * the final order is shuffled.
    """
    rng = rng or random.Random()
    pool = [t for t in tasks if t.difficulty == level]
    rng.shuffle(pool)
    if progress is None:
        return pool[:count]
    review = [t for t in pool if progress.missed_last_time(t.id)][:max_review]
    chosen = review[:count]
    rest = [t for t in pool if t not in chosen]
    rest.sort(key=lambda t: progress.seen(t.id))  # stable: random within equal counts
    chosen += rest[: count - len(chosen)]
    rng.shuffle(chosen)
    return chosen


def click_tolerance_deg(target, px_per_deg, clicked):
    """How far (in degrees) from ``target`` a click may land and still count.

    Normally 15 screen pixels. If the click landed inside a *different*
    country and the target is big enough to hit properly, only one pixel of
    slop is allowed - otherwise clicking Belgium would count as France on
    the whole-world view, where 15 pixels is about 300 km.
    """
    pixels = CLICK_TOLERANCE_PX
    if (target.kind == "country" and clicked is not None and clicked.kind == "country"
            and clicked is not target and target.size_deg * px_per_deg >= SMALL_TARGET_PX):
        pixels = BORDER_SLOP_PX
    return pixels / px_per_deg


@dataclass
class Outcome:
    kind: str                 # "correct", "close" or "wrong"
    clicked: object = None    # country/sea under the click (may be None)
    hit: object = None        # the target area that was hit, if correct
    star: bool = False        # correct without needing the answer shown
    hint_started: bool = False  # this miss was the third: now show the answer
    zone_started: bool = False  # this miss was the second: now show where to look
    wrong_attempts: int = 0


class Round:
    """One round of tasks. Feed it clicks; it never fails the player."""

    def __init__(self, world, tasks, progress=None, level=0, rng=None):
        self.rng = rng or random.Random()
        self.zone = None  # (lon0, lat0, lon1, lat1) once the "look here" box is shown
        self.world = world
        self.tasks = list(tasks)
        self.progress = progress
        self.level = level
        self.index = 0
        self.wrong_attempts = 0
        self.hint_active = False
        self.solved = False
        self.results = [None] * len(self.tasks)  # True = star, False = needed help

    @property
    def task(self):
        return self.tasks[self.index] if self.index < len(self.tasks) else None

    @property
    def finished(self):
        return self.index >= len(self.tasks)

    @property
    def stars(self):
        return sum(1 for r in self.results if r)

    def judge(self, lon, lat, px_per_deg):
        """What the rules say about a click here, without changing anything.

        Returns (kind, hit, clicked): kind is "correct", "close" or "wrong",
        ``hit`` the target that was hit (if correct) and ``clicked`` the
        country under the click (may be None).
        """
        areas = self.task.areas
        clicked = self.world.country_at(lon, lat)
        for target in areas:  # exact hits first, so a click inside a target is never ambiguous
            if target.contains(lon, lat):
                return "correct", target, clicked
        for target in areas:
            if target.hit(lon, lat, click_tolerance_deg(target, px_per_deg, clicked)):
                return "correct", target, clicked
        kind = "close" if self.world.is_close(areas, lon, lat, clicked) else "wrong"
        return kind, None, clicked

    def click(self, lon, lat, px_per_deg):
        """Judge a click at a map position, given the current zoom, and
        update the round accordingly."""
        task = self.task
        if task is None or self.solved:
            return None
        kind, hit, clicked_country = self.judge(lon, lat, px_per_deg)
        if hit is not None:
            self.solved = True
            star = not self.hint_active
            self.results[self.index] = star
            if self.progress is not None:
                self.progress.record(task.id, missed=self.wrong_attempts > 0, found=star)
                self.progress.save()
            return Outcome("correct", clicked_country, hit, star=star,
                           wrong_attempts=self.wrong_attempts)

        clicked = clicked_country or self.world.water_at(lon, lat)
        self.wrong_attempts += 1
        hint_started = False
        if not self.hint_active and self.wrong_attempts >= MAX_WRONG_ATTEMPTS:
            self.hint_active = True
            hint_started = True
        zone_started = False
        if self.zone is None and not self.hint_active and self.wrong_attempts >= ZONE_AFTER_WRONG:
            self.zone = search_zone(task.areas, self.rng)
            zone_started = True
        return Outcome(kind, clicked, hint_started=hint_started, zone_started=zone_started,
                       wrong_attempts=self.wrong_attempts)

    def advance(self):
        """Move to the next task. Returns False when the round is over."""
        self.index += 1
        self.zone = None
        self.wrong_attempts = 0
        self.hint_active = False
        self.solved = False
        if self.finished:
            if self.progress is not None:
                self.progress.record_round(self.level, self.stars)
                self.progress.save()
            return False
        return True
