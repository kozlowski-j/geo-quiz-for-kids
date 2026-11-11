"""Plays the real game automatically, as a player would, to check it works.

It opens the game window and feeds it genuine mouse events (move, press,
release, wheel): picks a level, answers every task - sometimes right away,
sometimes after a wrong click, a "close" click, or three misses and the hint
- tries zoom, pan, "whole map" and "repeat", and checks after every click
that the game reacted the way the rules say. Speech really speaks unless
--mute is given.

    python tools/smoke_play.py --level 1                 one normal round
    python tools/smoke_play.py --level 2 --all --mute    every level-2 task, fast
    python tools/smoke_play.py --level 3 --shots out/    also save screenshots

Exit code 0 means every check passed. Progress is written to a temporary
file, never to the real progress.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from geoquiz import tasks as T  # noqa: E402
from geoquiz.ui import App, MENU, PLAY, END  # noqa: E402
from geoquiz.view import LAT_MAX, LAT_MIN  # noqa: E402


class Bot:
    pending_check = None

    def __init__(self, app, level, play_all, shots):
        self.app = app
        self.level = level
        self.play_all = play_all
        self.shots = Path(shots) if shots else None
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
        self.wait = 30
        self.idle_frames = 0
        self.failures = []
        self.log = []
        self.plan = None          # pending steps for the current task
        self.plan_task = None
        self.task_no = 0
        self.stage = "menu"
        self.expected_stars = 0
        self.shot_names = set()

    # ---- helpers -----------------------------------------------------------
    def fail(self, text):
        self.failures.append(text)
        print("FAIL:", text)

    def shot(self, name):
        if not self.shots or name in self.shot_names:
            return
        self.shot_names.add(name)
        self.app.draw()
        pygame.image.save(self.app.screen, str(self.shots / f"L{self.level}_{name}.png"))

    def move(self, pos):
        pos = (int(pos[0]), int(pos[1]))
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))

    def click(self, pos):
        pos = (int(pos[0]), int(pos[1]))
        self.move(pos)
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))

    def drag(self, start, end):
        start = (int(start[0]), int(start[1]))
        end = (int(end[0]), int(end[1]))
        self.move(start)
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start, button=1))
        steps = 6
        prev = start
        for i in range(1, steps + 1):
            cur = (start[0] + (end[0] - start[0]) * i // steps, start[1] + (end[1] - start[1]) * i // steps)
            pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=cur,
                                                 rel=(cur[0] - prev[0], cur[1] - prev[1]), buttons=(1, 0, 0)))
            prev = cur
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1))

    def wheel(self, pos, y):
        self.move(pos)
        pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=y))

    def on_screen(self, lon, lat):
        app = self.app
        x, y = app.viewport.to_screen(lon, lat)
        if not app.viewport.contains_screen_point(x, y):
            return None
        # Keep clear of the buttons and the star row that float over the map.
        if any(b.rect.inflate(10, 10).collidepoint(x, y) for b in app.play_buttons):
            return None
        if y > app.H - app.H * 0.09:
            return None
        return (x, y)

    def judge(self, lon, lat):
        """What the rules say about a click here, without touching the round.

        The click lands on a whole pixel, so judge the map position of that
        pixel rather than the exact coordinates asked for."""
        app = self.app
        sx, sy = app.viewport.to_screen(lon, lat)
        lon, lat = app.viewport.to_world(int(sx), int(sy))
        return app.round.judge(lon, lat, app.viewport.scale)[0]

    @staticmethod
    def candidates():
        pts = []
        for lat in range(int(LAT_MIN) + 12, int(LAT_MAX) - 4, 6):
            for lon in range(-174, 180, 6):
                pts.append((lon + 0.37, lat + 0.41))
        return pts

    def find_point(self, kind):
        """A visible map point that the rules classify as ``kind``."""
        task = self.app.round.task
        if kind == "correct":
            for area in task.areas:
                for poly in sorted(area.polys, key=lambda p: -len(p[0])):
                    ring = poly[0]
                    cx = sum(p[0] for p in ring) / len(ring)
                    cy = sum(p[1] for p in ring) / len(ring)
                    tries = [(cx, cy)] + [((cx + p[0]) / 2, (cy + p[1]) / 2)
                                          for p in ring[:: max(1, len(ring) // 12)]]
                    for lon, lat in tries:
                        if (area.contains(lon, lat) and self.on_screen(lon, lat)
                                and self.judge(lon, lat) == "correct"):
                            return lon, lat
                for line in area.lines:
                    for lon, lat in line[len(line) // 2:] + line[: len(line) // 2]:
                        if self.on_screen(lon, lat) and self.judge(lon, lat) == "correct":
                            return lon, lat
        for lon, lat in self.candidates():
            if self.on_screen(lon, lat) and self.judge(lon, lat) == kind:
                return lon, lat
        return None

    # ---- per-task plans ------------------------------------------------------
    def make_plan(self):
        variant = self.task_no % 5
        if variant == 0:
            return ["correct"]
        if variant == 1:
            return ["wrong", "correct"]
        if variant == 2:
            return ["close", "repeat", "correct"]
        if variant == 3:
            return ["wrong", "close", "zone_check", "wrong", "hint_check", "wrong", "correct"]
        return ["zoom", "pan", "hover", "reset", "correct"]

    def do_step(self, step):
        app = self.app
        rnd = app.round
        task = rnd.task
        vp = app.viewport
        if step in ("correct", "wrong", "close"):
            point = self.find_point(step)
            if point is None:
                if step == "correct":
                    self.fail(f"{task.id}: could not find a visible correct point")
                    self.plan = ["give_up"]
                else:
                    self.log.append(f"{task.id}: no '{step}' point exists on screen, step skipped")
                return
            before = (rnd.wrong_attempts, rnd.hint_active, len(app.speaker.history))
            self.pending_check = (step, point, before, task)
            self.click(vp.to_screen(*point))
        elif step == "give_up":
            self.plan = ["give_up"]  # stay here; the run will time out and report
        elif step == "zone_check":
            zone = rnd.zone
            if zone is None:
                self.fail(f"{task.id}: no search box after {rnd.wrong_attempts} wrong clicks")
            else:
                anchor = max(task.areas, key=lambda a: a.size_deg).main_box
                if not (zone[0] <= anchor[0] + 1e-6 and zone[1] <= anchor[1] + 1e-6
                        and zone[2] >= min(anchor[2], 180) - 1e-6 and zone[3] >= min(anchor[3], 84) - 1e-6):
                    self.fail(f"{task.id}: search box {zone} does not contain the target {anchor}")
                if not app._zone_visible():
                    self.fail(f"{task.id}: search box is not fully on screen")
            self.shot("zone")
        elif step == "hint_check":
            if not rnd.hint_active:
                self.fail(f"{task.id}: hint not active after {rnd.wrong_attempts} wrong clicks")
            if not vp.is_default:
                self.fail(f"{task.id}: view was not reset when the hint started")
            self.shot("hint")
        elif step == "repeat":
            self.pending_check = ("repeat", None, len(app.speaker.history), task)
            self.click(app.repeat_button.rect.center)
        elif step == "zoom":
            self.zoom_from = vp.zoom
            pos = (vp.x + vp.width * 0.55, vp.y + vp.height * 0.4)
            for _ in range(5):
                self.wheel(pos, 1)
            self.pending_check = ("zoom", None, None, task)
        elif step == "pan":
            self.pan_from = (vp.center_lon, vp.center_lat)
            c = (vp.x + vp.width * 0.5, vp.y + vp.height * 0.5)
            self.drag(c, (c[0] - vp.width * 0.2, c[1] + vp.height * 0.15))
            self.pending_check = ("pan", None, None, task)
        elif step == "hover":
            self.move((vp.x + vp.width * 0.5, vp.y + vp.height * 0.5))
            self.pending_check = ("hover", None, None, task)
        elif step == "reset":
            self.shot("zoomed")
            self.click(app.reset_button.rect.center)
            self.pending_check = ("reset", None, None, task)

    def check_step(self):
        step, point, before, task = self.pending_check
        self.pending_check = None
        app = self.app
        rnd = app.round
        vp = app.viewport
        tid = task.id
        if step == "correct":
            if not (app.phase == "celebrate" or rnd.task is not task or app.state == END):
                self.fail(f"{tid}: correct click at {point} was not accepted")
            else:
                self.log.append(f"{tid}: ok")
                if not before[1]:
                    self.expected_stars += 1
                self.shot("celebrate")
        elif step in ("wrong", "close"):
            if rnd.wrong_attempts != before[0] + 1:
                self.fail(f"{tid}: {step} click at {point} did not count as a miss")
            said = app.speaker.history[-1] if len(app.speaker.history) > before[2] else ""
            phrases = app.strings.data["speech"]["close" if step == "close" else "wrong"]
            if not before[1] and rnd.wrong_attempts < T.ZONE_AFTER_WRONG:
                if not any(said.startswith(p) for p in phrases):
                    self.fail(f"{tid}: after a {step} click the game said {said!r}")
            if app.strings.speech("that_is", name="\x00").split("\x00")[0] not in said:
                self.fail(f"{tid}: the game did not name the clicked place: {said!r}")
            if app.phase != "asking":
                self.fail(f"{tid}: game left the asking phase after a miss")
            self.shot("miss_" + step)
        elif step == "repeat":
            if len(app.speaker.history) != before + 1 or app.speaker.history[-1] != app.strings.prompt(task):
                self.fail(f"{tid}: Repeat did not re-speak the prompt")
        elif step == "zoom":
            if not vp.zoom > self.zoom_from * 2:
                self.fail(f"{tid}: mouse wheel did not zoom (zoom={vp.zoom})")
        elif step == "pan":
            if (vp.center_lon, vp.center_lat) == self.pan_from:
                self.fail(f"{tid}: dragging did not pan the map")
            if rnd.wrong_attempts or app.phase != "asking":
                self.fail(f"{tid}: a drag was treated as a click")
        elif step == "hover":
            expect = app.world.country_at(*vp.to_world(*app.last_mouse))
            if app.hover_area is not expect:
                self.fail(f"{tid}: hover highlight {app.hover_area} != {expect}")
        elif step == "reset":
            if not vp.is_default:
                self.fail(f"{tid}: Whole map button did not reset the view")

    # ---- called every frame ---------------------------------------------------
    def __call__(self, app):
        if self.wait > 0:
            self.wait -= 1
            return
        if self.pending_check is not None:
            self.check_step()
            self.wait = 4
            return
        if app.state == MENU:
            if self.stage == "menu":
                self.shot("menu")
                if self.play_all:
                    pool = [t for t in app.tasks if t.difficulty == self.level]
                    app.start_round(self.level, tasks=pool)
                else:
                    self.click(app.level_buttons[self.level - 1].rect.center)
                self.stage = "play"
                self.wait = 10
            elif self.stage == "back_in_menu":
                self.click(app.quit_button.rect.center)
                self.stage = "quit"
                self.wait = 10
            return
        if app.state == PLAY:
            if self.stage == "second_round":
                # "Play again" worked; now check the Menu button and leave.
                if app.round.index != 0 or app.phase != "asking":
                    self.fail("Play again did not start a fresh round")
                self.click(app.home_button.rect.center)
                self.stage = "back_in_menu"
                self.wait = 15
                return
            if app.phase != "asking":
                self.plan = None
                return
            if app.picture_intro_active:
                return  # the big picture is still up
            # Let the spoken prompt finish, as a child would (bounded wait).
            if app.speaker.busy and self.idle_frames < 600:
                self.idle_frames += 1
                return
            self.idle_frames = 0
            task = app.round.task
            if self.plan is None or self.plan_task is not task:
                self.plan = self.make_plan()
                self.plan_task = task
                self.task_no += 1
                if app.speaker.history[-1:] != [app.strings.prompt(task)]:
                    self.fail(f"{task.id}: prompt was not spoken at task start")
                if not app.viewport.is_default:
                    self.fail(f"{task.id}: view not reset at task start")
                self.shot("task")
            if self.plan:
                self.do_step(self.plan.pop(0))
                self.wait = 6
            return
        if app.state == END:
            if self.stage == "play":
                rnd = app.round
                if rnd.stars != self.expected_stars:
                    self.fail(f"end screen shows {rnd.stars} stars, expected {self.expected_stars}")
                if not self.play_all and len(rnd.tasks) != T.ROUND_LENGTH:
                    self.fail(f"round had {len(rnd.tasks)} tasks, expected {T.ROUND_LENGTH}")
                if len(set(t.id for t in rnd.tasks)) != len(rnd.tasks):
                    self.fail("a task was repeated within the round")
                self.stage = "end_wait"
                self.wait = 200  # let the stars animate and the summary start
            elif self.stage == "end_wait":
                self.shot("end")
                self.click(app.again_button.rect.center)
                self.stage = "second_round"
                self.wait = 20


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--level", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--all", action="store_true", help="play every task of the level, not just 10")
    parser.add_argument("--mute", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--shots", help="folder for screenshots")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--lang", default="en", help="language to play in (en, pl)")
    parser.add_argument("--timeout", type=float, default=600.0, help="give up after this many seconds")
    args = parser.parse_args()

    import time

    with tempfile.TemporaryDirectory() as tmp:
        progress = Path(tmp) / "progress.json"
        app = App(fullscreen=not args.windowed, speak=not args.mute, sound=not args.mute,
                  progress_file=progress, seed=args.seed)
        app.set_language(args.lang)
        if app.strings.language != args.lang:
            sys.exit(f"language {args.lang!r} is not available")
        bot = Bot(app, args.level, args.all, args.shots)
        speech_ok = app.speaker.available
        voice = app.speaker.voice_name
        deadline = time.monotonic() + args.timeout
        frame_ms = []

        def driver(a):
            frame_ms.append(a.clock.get_rawtime())
            if time.monotonic() > deadline:
                bot.fail("timed out")
                a.running = False
                return
            bot(a)

        app.run(driver=driver)
        for sentence in sorted(app.speaker.missing):
            bot.fail(f"no voice clip for {sentence!r}")
        saved = json.loads(progress.read_text(encoding="utf-8")) if progress.exists() else {}

    played = [l for l in bot.log if l.endswith(": ok")]
    frame_ms.sort()
    print(f"level {args.level}: {len(played)} tasks answered, {len(bot.failures)} failures, "
          f"speech={'on (' + voice + ')' if speech_ok else 'off'}, "
          f"progress saved for {len(saved.get('tasks', {}))} tasks, best={saved.get('best')}")
    if frame_ms:
        print(f"  frame time ms: median {frame_ms[len(frame_ms) // 2]}, "
              f"95% {frame_ms[int(len(frame_ms) * 0.95)]}, worst {frame_ms[-1]}")
    for line in bot.log:
        if not line.endswith(": ok"):
            print("  note:", line)
    if bot.stage != "quit" and not bot.failures:
        print(f"FAIL: run ended early in stage {bot.stage!r}")
        sys.exit(1)
    sys.exit(1 if bot.failures else 0)


if __name__ == "__main__":
    main()
