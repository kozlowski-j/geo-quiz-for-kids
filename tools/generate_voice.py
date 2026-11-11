"""Generate the game's voice clips with ElevenLabs.

The game itself is offline: it only plays the mp3 files this tool creates in
data/voice/<language>/. Run it again after changing any spoken text (task
prompts in data/tasks.json, phrases or names in data/strings.json); only
sentences that have no clip yet are generated, so reruns are cheap.

    python tools/generate_voice.py --lang pl        the same for Polish (data/strings.pl.json)
    python tools/generate_voice.py --dry-run        show what would be generated and the cost
    python tools/generate_voice.py                  generate every missing clip
    python tools/generate_voice.py --limit 5        generate only the first 5 missing clips
    python tools/generate_voice.py --redo "That is Germany."   make one clip again
    python tools/generate_voice.py --prune          delete clips no sentence uses any more

The API key is read from the environment variable ELEVENLABS_API_KEY or from
a .env file in the project folder (ELEVENLABS_API_KEY=...). It is never
printed or stored anywhere else.

Credits: with the default model a character costs about 0.4 credits (the
English set, 10,800 characters, cost 4,374). The run prints the exact total. Two safety limits stop the tool before it spends anything:
  --budget   the most characters one run may generate   (default 15000)
  --reserve  credits that must remain afterwards         (default 20000;
             only checked if the API key is allowed to read the balance)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from geoquiz.mapdata import WorldMap  # noqa: E402
from geoquiz.strings import Strings  # noqa: E402
from geoquiz.tasks import load_tasks  # noqa: E402
from geoquiz.voice_lines import all_lines, clip_name, VOICE_FOLDER  # noqa: E402

API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE = "DODLEQrClDo8wCz460ld"   # "Lauren"
DEFAULT_MODEL = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_64"           # small files, plenty for speech
DEFAULT_SPEED = 0.92                     # a little slower than normal, for a child


def load_env_file():
    """Minimal .env reader: KEY=VALUE lines, optional quotes, # comments."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class ApiError(Exception):
    pass


last_cost = 0  # credits charged for the most recent request, as reported by the API


def request(method, url, key, body=None, timeout=120):
    global last_cost
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"xi-api-key": key, "Accept": "*/*"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            try:
                last_cost = int(response.headers.get("character-cost") or 0)
            except ValueError:
                last_cost = 0
            return response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:500]
        raise ApiError(f"HTTP {err.code}: {detail}") from None
    except urllib.error.URLError as err:
        raise ApiError(f"network error: {err.reason}") from None


def credits(key):
    """(used, limit) of the account, or None if it cannot be read."""
    try:
        info = json.loads(request("GET", f"{API}/user/subscription", key))
        return int(info["character_count"]), int(info["character_limit"])
    except (ApiError, KeyError, ValueError, TypeError):
        return None


def synthesise(text, key, voice, model, speed, context=None):
    url = f"{API}/text-to-speech/{voice}?output_format={OUTPUT_FORMAT}"
    body = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": speed},
    }
    if context:
        # Tells the model what came "before", so a short sentence such as
        # "To Iran." is read in the right language instead of being guessed.
        body["previous_text"] = context
    for attempt in range(5):
        try:
            return request("POST", url, key, body)
        except ApiError as err:
            message = str(err)
            if message.startswith(("HTTP 429", "HTTP 5", "network error")) and attempt < 4:
                time.sleep(2 + attempt * 4)  # rate limit or hiccup: wait and retry
                continue
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only show what would be generated")
    parser.add_argument("--limit", type=int, help="generate at most this many clips")
    parser.add_argument("--redo", action="append", default=[], metavar="SENTENCE",
                        help="regenerate the clip of this exact sentence (repeatable)")
    parser.add_argument("--prune", action="store_true", help="delete clips that are no longer used")
    parser.add_argument("--budget", type=int, default=15000, help="max characters to generate in this run")
    parser.add_argument("--reserve", type=int, default=20000, help="credits that must be left afterwards")
    parser.add_argument("--lang", default="en", help="language to generate: en, pl, ... (default en)")
    parser.add_argument("--voice", help="ElevenLabs voice id (default: \"voice_id\" in the "
                        "language's strings file)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED)
    args = parser.parse_args()

    world = WorldMap.load()
    strings = Strings.load(language=args.lang)
    context = strings.data.get("voice_context")  # set in the non-English strings files
    voice = args.voice or strings.data.get("voice_id") or DEFAULT_VOICE
    tasks, problems = load_tasks(world)
    for problem in problems:
        print("tasks.json:", problem)
    lines = all_lines(world, strings, tasks)
    folder = ROOT / VOICE_FOLDER / strings.language
    folder.mkdir(parents=True, exist_ok=True)
    wanted = {clip_name(text): text for text in lines}

    redo = {" ".join(t.split()) for t in args.redo}
    unknown = redo - set(lines)
    if unknown:
        sys.exit(f"--redo: the game never says: {sorted(unknown)}")
    todo = [text for text in lines if text in redo or not (folder / clip_name(text)).exists()]
    if args.limit is not None:
        todo = todo[: args.limit]
    chars = sum(len(t) for t in todo)
    have = sum(1 for name in wanted if (folder / name).exists())
    print(f"{len(lines)} sentences ({sum(len(t) for t in lines)} characters) in language "
          f"'{strings.language}'; {have} clips exist; {len(todo)} to generate = {chars} characters")

    stale = sorted(p.name for p in folder.glob("*.mp3") if p.name not in wanted)
    if stale:
        print(f"{len(stale)} clips are no longer used" + ("" if args.prune else " (--prune deletes them)"))
        if args.prune and not args.dry_run:
            for name in stale:
                (folder / name).unlink()

    if args.dry_run:
        for text in todo[:15]:
            print("   ", text)
        if len(todo) > 15:
            print(f"    ... and {len(todo) - 15} more")
        return
    if todo:
        if chars > args.budget:
            sys.exit(f"Stopped: {chars} characters is over the --budget of {args.budget}.")
        load_env_file()
        key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not key:
            sys.exit("Stopped: ELEVENLABS_API_KEY is not set (environment or .env file).")
        before = credits(key)
        if before is None:
            # A key limited to text-to-speech cannot read the balance. The
            # character budget above is then the only (but hard) limit.
            print(f"note: this API key cannot read the credit balance, so --reserve is not "
                  f"checked. This run will use about {round(chars * 0.4)} credits.")
        else:
            left = before[1] - before[0]
            print(f"credits: {left} left of {before[1]}")
            if left - chars < args.reserve:
                sys.exit(f"Stopped: generating {chars} characters would leave about {left - chars} "
                         f"credits, less than the --reserve of {args.reserve}.")

        print(f"voice: {strings.data.get('voice_name', '') if not args.voice else ''} {voice}".replace("  ", " "))
        done = 0
        spent = 0
        try:
            for number, text in enumerate(todo, 1):
                audio = synthesise(text, key, voice, args.model, args.speed, context)
                if len(audio) < 500:
                    raise ApiError(f"suspiciously small audio for {text!r}")
                target = folder / clip_name(text)
                tmp = target.with_suffix(".part")
                tmp.write_bytes(audio)
                os.replace(tmp, target)
                done += 1
                spent += last_cost
                if number % 25 == 0 or number == len(todo):
                    print(f"  {number}/{len(todo)}")
        except ApiError as err:
            print(f"Stopped after {done} clips: {err}")
        except KeyboardInterrupt:
            print(f"Interrupted after {done} clips.")
        after = credits(key)
        if after is not None and before is not None:
            print(f"generated {done} clips; credits used by this run: {after[0] - before[0]}; "
                  f"{after[1] - after[0]} left")
        else:
            print(f"generated {done} clips; credits charged for this run: {spent}")

    # A readable index of which file says what (the game does not need it).
    index = {name: text for name, text in sorted(wanted.items(), key=lambda kv: kv[1])
             if (folder / name).exists()}
    (folder / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    missing = len(wanted) - len(index)
    print(f"{len(index)} of {len(wanted)} sentences have a clip" + (f"; {missing} still missing" if missing else ""))


if __name__ == "__main__":
    main()
