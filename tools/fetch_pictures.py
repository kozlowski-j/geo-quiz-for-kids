"""Download the pictures shown with animal and landmark questions.

The game itself is offline: it only shows the files this tool saves in
data/pictures/. The list of what to fetch is data/pictures/sources.json; each
entry names an English Wikipedia article (its main picture is used) or an
exact Wikimedia Commons file. Only freely licensed pictures are accepted, and
the author and licence of each one are written to data/pictures/credits.json
and data/pictures/CREDITS.md, as those licences require.

    python tools/fetch_pictures.py                 fetch every picture not downloaded yet
    python tools/fetch_pictures.py --force lion    download this one again (repeatable)
    python tools/fetch_pictures.py --sheet out     also save contact sheets (overview images)
    python tools/fetch_pictures.py --search "Burj Khalifa"    list Commons photos to choose from

To use a different picture, put its Commons file name into sources.json as
{"file": "Some photo.jpg"} and run the tool with --force <id>.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "data" / "pictures"
REQUEST_WIDTH = 960  # one of Wikimedia's standard thumbnail sizes (others are throttled hard)
WIDTH = 640          # what is kept: plenty for a card on a full-HD screen
USER_AGENT = "WorldExplorerPictureFetcher/1.0 (offline educational game; python-urllib)"
EXTENSIONS = (".jpg", ".png", ".webp")
FREE = re.compile(r"^(cc0|cc[ -]by|public domain|pd|no restrictions|attribution|gfdl|fal|ogl)", re.I)


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(20 + attempt * 40)  # rate limited: wait it out
                continue
            raise


def api(host, **params):
    params.update(format="json", formatversion="2")
    return get(f"https://{host}/w/api.php?" + urllib.parse.urlencode(params))


def lead_image(article):
    """File name of the free main picture of an English Wikipedia article."""
    data = api("en.wikipedia.org", action="query", titles=article, redirects="1",
               prop="pageimages", piprop="name", pilicense="free")
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        raise LookupError(f"no Wikipedia article called {article!r}")
    name = pages[0].get("pageimage")
    if not name:
        raise LookupError(f"article {article!r} has no free main picture")
    return "File:" + name


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return " ".join(html.unescape(text).split())


def file_info(title):
    data = api("commons.wikimedia.org", action="query", titles=title, prop="imageinfo",
               iiprop="url|extmetadata|mime", iiurlwidth=str(REQUEST_WIDTH))
    pages = data.get("query", {}).get("pages", [])
    if not pages or "imageinfo" not in pages[0]:
        raise LookupError(f"no Commons file called {title!r}")
    info = pages[0]["imageinfo"][0]
    meta = {k: v.get("value", "") for k, v in info.get("extmetadata", {}).items()}
    licence = clean(meta.get("LicenseShortName", ""))
    if not FREE.match(licence):
        raise LookupError(f"{title}: licence {licence!r} is not a free licence")
    return {
        "file": pages[0]["title"],
        "thumb": info.get("thumburl") or info["url"],
        "page": info.get("descriptionurl", ""),
        "author": clean(meta.get("Artist", "")) or "unknown",
        "licence": licence,
        "licence_url": meta.get("LicenseUrl", ""),
    }


def shrink(path):
    """Scale a downloaded picture to WIDTH and store it as a compact JPEG."""
    import pygame

    image = pygame.image.load(str(path))
    if image.get_width() > WIDTH:
        height = round(image.get_height() * WIDTH / image.get_width())
        image = pygame.transform.smoothscale(image.convert_alpha() if image.get_alpha() else image.convert(24),
                                             (WIDTH, height))
    flat = pygame.Surface(image.get_size())
    flat.fill((255, 255, 255))  # JPEG has no transparency
    flat.blit(image, (0, 0))
    target = path.with_suffix(".jpg")
    pygame.image.save(flat, str(target))
    if target != path:
        path.unlink()
    return target


def existing(picture_id):
    for ext in EXTENSIONS:
        path = FOLDER / (picture_id + ext)
        if path.exists():
            return path
    return None


def contact_sheets(ids, out):
    """Overview images of all pictures, for checking them at a glance."""
    import pygame

    pygame.init()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    font = pygame.font.SysFont("arial", 18, bold=True)
    cols, rows, cw, ch = 5, 4, 256, 210
    for start in range(0, len(ids), cols * rows):
        sheet = pygame.Surface((cols * cw, rows * ch))
        sheet.fill((255, 255, 255))
        for n, picture_id in enumerate(ids[start:start + cols * rows]):
            x, y = (n % cols) * cw, (n // cols) * ch
            path = existing(picture_id)
            if path:
                image = pygame.image.load(str(path))
                scale = min((cw - 8) / image.get_width(), (ch - 30) / image.get_height())
                image = pygame.transform.smoothscale(
                    image, (int(image.get_width() * scale), int(image.get_height() * scale)))
                sheet.blit(image, (x + (cw - image.get_width()) // 2, y + 4))
            label = font.render(picture_id + ("" if path else "  MISSING"), True, (200, 0, 0) if not path else (0, 0, 0))
            sheet.blit(label, (x + 6, y + ch - 24))
        pygame.image.save(sheet, str(out / f"sheet{start // (cols * rows) + 1}.png"))
    pygame.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="append", default=[], metavar="ID", help="download this picture again")
    parser.add_argument("--shrink-all", action="store_true", help="re-compress the pictures already present")
    parser.add_argument("--search", metavar="WORDS", help="list matching photos on Wikimedia Commons and stop")
    parser.add_argument("--sheet", metavar="FOLDER", help="save contact sheets of all pictures here")
    args = parser.parse_args()

    if args.search:
        found = api("commons.wikimedia.org", action="query", list="search", srnamespace="6",
                    srlimit="15", srsearch=args.search + " filetype:bitmap")
        for hit in found.get("query", {}).get("search", []):
            print(" ", hit["title"])
        return

    sources = {k: v for k, v in json.loads((FOLDER / "sources.json").read_text(encoding="utf-8")).items()
               if not k.startswith("_")}
    credits_path = FOLDER / "credits.json"
    credits = json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.exists() else {}
    unknown = [i for i in args.force if i not in sources]
    if unknown:
        sys.exit(f"--force: not in sources.json: {unknown}")

    failed = []
    if args.shrink_all:
        for picture_id in sources:
            if existing(picture_id):
                shrink(existing(picture_id))
    for picture_id, source in sources.items():
        if existing(picture_id) and picture_id in credits and picture_id not in args.force:
            continue
        try:
            title = source.get("file") or lead_image(source["article"])
            if not title.startswith("File:"):
                title = "File:" + title
            info = file_info(title)
            data = get(info["thumb"], binary=True)
            ext = ".png" if info["thumb"].lower().endswith(".png") else ".webp" if info["thumb"].lower().endswith(".webp") else ".jpg"
            for old in EXTENSIONS:
                (FOLDER / (picture_id + old)).unlink(missing_ok=True)
            (FOLDER / (picture_id + ext)).write_bytes(data)
            shrink(FOLDER / (picture_id + ext))
            credits[picture_id] = {k: info[k] for k in ("file", "author", "licence", "licence_url", "page")}
            print(f"  {picture_id}: {info['file']}  [{info['licence']}]")
            time.sleep(1.5)
        except (LookupError, urllib.error.URLError, KeyError) as err:
            failed.append(picture_id)
            print(f"  {picture_id}: FAILED - {err}")

    credits = {k: credits[k] for k in sources if k in credits}
    credits_path.write_text(json.dumps(credits, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = ["# Picture credits", "",
             "The pictures in this folder come from Wikimedia Commons and are used under the",
             "licences below. Each was scaled down; some are cropped on screen.", ""]
    for picture_id, c in credits.items():
        lines.append(f"- **{picture_id}**: [{c['file'].removeprefix('File:')}]({c['page']}) by {c['author']}, "
                     f"{c['licence']}" + (f" ({c['licence_url']})" if c["licence_url"] else ""))
    (FOLDER / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    have = sum(1 for i in sources if existing(i))
    print(f"{have} of {len(sources)} pictures present" + (f"; failed: {failed}" if failed else ""))
    if args.sheet:
        contact_sheets(list(sources), args.sheet)


if __name__ == "__main__":
    main()
