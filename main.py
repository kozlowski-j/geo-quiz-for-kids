"""World Explorer - a geography quiz for young children.

Run with:  python main.py            (fullscreen, Esc to exit)
Options:   --windowed   run in a 1280x720 window
           --mute       no speech and no sounds
           --selftest   start, open a level for a moment, and exit again;
                        exit code 0 = everything loaded, 2 = something is
                        broken (tasks, a missing voice clip, or no round
                        started), 3 = fine but no speech voice / audio device
"""
from __future__ import annotations

import argparse
import sys


def selftest():
    """Quick check that the app (especially a packaged .exe) can start:
    bundled data loads, a window opens, a round starts, speech initialises."""
    import tempfile
    from pathlib import Path

    from geoquiz.ui import App, PLAY

    with tempfile.TemporaryDirectory() as tmp:
        app = App(fullscreen=False, speak=True, sound=False, progress_file=Path(tmp) / "progress.json")
        app.speaker.stop()
        result = {"speech": app.speaker.available, "played": False, "tasks": len(app.tasks),
                  "problems": len(app.task_problems)}

        def driver(a):
            if a.frame == 30:
                a.press(("level", 1))
                a.speaker.stop()
            elif a.frame == 60:
                result["played"] = a.state == PLAY and a.round is not None
                a.running = False

        app.run(driver=driver)
        result["missing"] = len(app.speaker.missing)  # sentences spoken without a clip
    if not result["played"] or result["tasks"] < 30 or result["problems"] or result["missing"]:
        return 2
    return 0 if result["speech"] else 3


def main():
    parser = argparse.ArgumentParser(description="Geography quiz for kids")
    parser.add_argument("--windowed", action="store_true", help="run in a window instead of fullscreen")
    parser.add_argument("--mute", action="store_true", help="disable speech and sound")
    parser.add_argument("--selftest", action="store_true", help="start, check everything loads, exit")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(selftest())

    try:
        from geoquiz.ui import App

        app = App(fullscreen=not args.windowed, speak=not args.mute, sound=not args.mute)
    except Exception as exc:  # most likely a typo in a hand-edited JSON file
        show_startup_error(exc)
        raise
    app.run()


def show_startup_error(exc):
    """The packaged game has no console, so say what went wrong in a dialog."""
    try:
        import ctypes

        import pygame

        pygame.quit()
        text = (f"World Explorer could not start.\n\n{type(exc).__name__}: {exc}\n\n"
                "If you edited a file in the data folder, check it for typos "
                "(a missing comma or quote is the usual cause).")
        ctypes.windll.user32.MessageBoxW(None, text, "World Explorer", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    main()
