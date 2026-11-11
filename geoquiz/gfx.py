"""Small drawing toolkit for the UI: smooth rounded panels with soft shadows,
stars, icons and fonts. Shapes are drawn at three times their size and
scaled down, which gives clean anti-aliased edges; results are cached.
"""
from __future__ import annotations

import math
from functools import lru_cache

import pygame

from .paths import resource_path

SS = 3  # supersampling factor

INK = (36, 48, 78)            # main text colour
INK_SOFT = (110, 122, 150)    # secondary text
WHITE = (255, 255, 255)
GOLD = (255, 198, 52)
EMPTY = (218, 225, 236)

_fonts = {}


def font(size, weight="extrabold"):
    """Bundled Nunito in the given pixel size (falls back to Segoe UI)."""
    size = max(8, int(size))
    key = (size, weight)
    if key not in _fonts:
        name = "Nunito-ExtraBold.ttf" if weight == "extrabold" else "Nunito-Bold.ttf"
        try:
            _fonts[key] = pygame.font.Font(str(resource_path(f"data/fonts/{name}")), size)
        except (OSError, pygame.error):
            _fonts[key] = pygame.font.SysFont("segoeui,verdana,arial", size, bold=True)
    return _fonts[key]


def reset_caches():
    """Forget every cached font and surface. They die with ``pygame.quit()``,
    so this must be called before pygame is started a second time."""
    _fonts.clear()
    for cached in (panel, star, icon, vertical_gradient, flag, arrow, picture, pin):
        cached.cache_clear()


def soft_blur(surface, radius):
    """Gaussian blur. A blurred image holds no fine detail, so a large blur
    is done on a shrunken copy and scaled back up: it looks the same and
    takes a small fraction of the time."""
    radius = max(1, int(radius))
    shrink = radius // 3
    w, h = surface.get_size()
    if shrink < 2 or w < shrink * 8 or h < shrink * 8:
        return pygame.transform.gaussian_blur(surface, radius)
    small = pygame.transform.smoothscale(surface, (w // shrink, h // shrink))
    small = pygame.transform.gaussian_blur(small, max(1, round(radius / shrink)))
    return pygame.transform.smoothscale(small, (w, h))


def lighten(color, amount):
    return tuple(int(c + (255 - c) * amount) for c in color[:3])


def darken(color, amount):
    return tuple(int(c * (1 - amount)) for c in color[:3])


@lru_cache(maxsize=256)
def panel(size, color, radius, shadow=10, gradient=0.0):
    """A rounded rectangle with an optional soft drop shadow.

    Returns (surface, margin): blit the surface at (x - margin, y - margin)
    to place the panel itself at (x, y). ``gradient`` > 0 lightens the top.
    """
    w, h = int(size[0]), int(size[1])
    radius = int(min(radius, w / 2, h / 2))
    big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
    big.fill((*color, 0))  # transparent, but already the right colour: no dark fringe when scaled
    pygame.draw.rect(big, (*color, 255), big.get_rect(), border_radius=radius * SS)
    if gradient:
        shade = pygame.Surface((1, 64), pygame.SRCALPHA)
        top = lighten(color, gradient)
        for y in range(64):
            t = y / 63
            shade.set_at((0, y), tuple(int(top[i] + (color[i] - top[i]) * t) for i in range(3)) + (255,))
        shade = pygame.transform.smoothscale(shade, big.get_size())
        mask = big.copy()
        mask.fill((255, 255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)
        shade.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        big = shade
    body = pygame.transform.smoothscale(big, (w, h))
    margin = int(shadow * 2) if shadow else 0
    if not margin:
        return body, 0
    out = pygame.Surface((w + 2 * margin, h + 2 * margin), pygame.SRCALPHA)
    pygame.draw.rect(out, (20, 40, 80, 70), pygame.Rect(margin, margin + shadow // 2, w, h),
                     border_radius=radius)
    out = soft_blur(out, shadow)
    out.blit(body, (margin, margin))
    return out, margin


def draw_panel(screen, rect, color, radius, shadow=10, gradient=0.0):
    surf, margin = panel((rect.width, rect.height), tuple(color), int(radius), int(shadow), gradient)
    screen.blit(surf, (rect.x - margin, rect.y - margin))


def _star_points(cx, cy, radius):
    pts = []
    for i in range(10):
        r = radius if i % 2 == 0 else radius * 0.5
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


@lru_cache(maxsize=128)
def star(radius, color=GOLD):
    """A plump star with rounded points, as a surface of side 2*radius+4."""
    radius = max(3, int(radius))
    side = (radius * 2 + 4) * SS
    big = pygame.Surface((side, side), pygame.SRCALPHA)
    big.fill((*color, 0))
    c = side / 2
    r = radius * SS
    filled = color == GOLD
    pts = _star_points(c, c + r * 0.05, r * 0.86)
    pygame.draw.polygon(big, color, pts)
    # Thick same-colour outline with round joints rounds off the tips.
    width = max(2, int(r * 0.28))
    pygame.draw.lines(big, color, True, pts, width)
    for p in pts:
        pygame.draw.circle(big, color, p, width // 2)
    if filled:  # a soft highlight on the upper-left arm
        pygame.draw.circle(big, lighten(GOLD, 0.55), (c - r * 0.2, c - r * 0.2), max(2, int(r * 0.13)))
    return pygame.transform.smoothscale(big, (side // SS, side // SS))


def draw_star(screen, cx, cy, radius, color=GOLD, angle=0.0):
    surf = star(int(radius), tuple(color))
    if angle:
        surf = pygame.transform.rotozoom(surf, angle, 1.0)
    screen.blit(surf, surf.get_rect(center=(int(cx), int(cy))))


@lru_cache(maxsize=64)
def icon(name, size, color=WHITE):
    """Simple pictograms: speaker, globe, home, plus, minus."""
    size = max(8, int(size))
    s = size * SS
    big = pygame.Surface((s, s), pygame.SRCALPHA)
    big.fill((*color, 0))
    c = s / 2
    w = max(SS * 2, int(s * 0.11))
    if name == "speaker":
        body = [(s * 0.06, s * 0.36), (s * 0.26, s * 0.36), (s * 0.50, s * 0.14),
                (s * 0.50, s * 0.86), (s * 0.26, s * 0.64), (s * 0.06, s * 0.64)]
        pygame.draw.polygon(big, color, body)
        pygame.draw.lines(big, color, True, body, max(2, w // 2))
        for k in (0.20, 0.36):
            arc = pygame.Rect(0, 0, int(s * k * 2), int(s * k * 2))
            arc.center = (int(s * 0.54), int(c))
            pygame.draw.arc(big, color, arc, -math.pi / 3.4, math.pi / 3.4, w)
    elif name == "globe":
        rad = int(s * 0.44)
        pygame.draw.circle(big, color, (c, c), rad, w)
        pygame.draw.ellipse(big, color, pygame.Rect(c - rad * 0.48, c - rad, rad * 0.96, rad * 2), w)
        pygame.draw.line(big, color, (c - rad, c), (c + rad, c), w)
    elif name == "home":
        roof = [(c, s * 0.08), (s * 0.94, s * 0.50), (s * 0.06, s * 0.50)]
        pygame.draw.polygon(big, color, roof)
        pygame.draw.lines(big, color, True, roof, w)
        pygame.draw.rect(big, color, pygame.Rect(s * 0.20, s * 0.46, s * 0.60, s * 0.46),
                         border_radius=int(s * 0.06))
    elif name in ("plus", "minus"):
        pygame.draw.line(big, color, (s * 0.16, c), (s * 0.84, c), int(w * 1.5))
        pygame.draw.circle(big, color, (s * 0.16, c), int(w * 0.75))
        pygame.draw.circle(big, color, (s * 0.84, c), int(w * 0.75))
        if name == "plus":
            pygame.draw.line(big, color, (c, s * 0.16), (c, s * 0.84), int(w * 1.5))
            pygame.draw.circle(big, color, (c, s * 0.16), int(w * 0.75))
            pygame.draw.circle(big, color, (c, s * 0.84), int(w * 0.75))
    return pygame.transform.smoothscale(big, (size, size))


@lru_cache(maxsize=8)
def vertical_gradient(size, top, bottom):
    strip = pygame.Surface((1, 128))
    for y in range(128):
        t = y / 127
        strip.set_at((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return pygame.transform.smoothscale(strip, size)


@lru_cache(maxsize=16)
def flag(code, height):
    """A small rounded flag for a language: "pl" Poland, "en" United States.
    Returns None for a language without a drawn flag."""
    if code not in ("pl", "en"):
        return None
    h = max(12, int(height)) * SS
    w = int(h * 1.5)
    big = pygame.Surface((w, h), pygame.SRCALPHA)
    if code == "pl":
        big.fill((255, 255, 255, 255))
        pygame.draw.rect(big, (220, 20, 60), (0, h // 2, w, h - h // 2))
    else:
        big.fill((255, 255, 255, 255))
        stripe = h / 13
        for i in range(0, 13, 2):
            pygame.draw.rect(big, (190, 40, 58), (0, round(i * stripe), w, round(stripe) + 1))
        canton = pygame.Rect(0, 0, int(w * 0.42), round(stripe * 7))
        pygame.draw.rect(big, (52, 60, 120), canton)
        rows, cols = 5, 6  # a simplified field of stars that still reads at button size
        for r in range(rows):
            n = cols if r % 2 == 0 else cols - 1
            for c in range(n):
                x = canton.width * (c + (0.5 if r % 2 == 0 else 1.0)) / cols
                y = canton.height * (r + 0.5) / rows
                pygame.draw.circle(big, WHITE, (x, y), max(2, h * 0.022))
    radius = int(h * 0.16)
    pygame.draw.rect(big, (205, 212, 226), big.get_rect(), max(2, SS), border_radius=radius)
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    big.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return pygame.transform.smoothscale(big, (w // SS, h // SS))


@lru_cache(maxsize=32)
def arrow(size, color, direction):
    """A chunky arrow with a white edge. direction: "right", "left", "up" or "down"."""
    size = max(12, int(size))
    s = size * SS
    big = pygame.Surface((s, s), pygame.SRCALPHA)
    big.fill((255, 255, 255, 0))
    shape = [(s * 0.06, s * 0.36), (s * 0.50, s * 0.36), (s * 0.50, s * 0.12), (s * 0.94, s * 0.50),
             (s * 0.50, s * 0.88), (s * 0.50, s * 0.64), (s * 0.06, s * 0.64)]
    edge = max(SS * 2, int(s * 0.09))
    pygame.draw.polygon(big, WHITE, shape)
    pygame.draw.lines(big, WHITE, True, shape, edge * 2)
    for point in shape:
        pygame.draw.circle(big, WHITE, point, edge)
    pygame.draw.polygon(big, color, shape)
    pygame.draw.lines(big, color, True, shape, max(2, edge // 3))
    image = pygame.transform.smoothscale(big, (size, size))
    turn = {"right": 0, "up": 90, "left": 180, "down": 270}[direction]
    return pygame.transform.rotate(image, turn) if turn else image


_picture_files = {}


def picture_path(picture_id):
    """File of a picture in data/pictures, or None if there is none."""
    if picture_id not in _picture_files:
        found = None
        if picture_id:
            for ext in (".jpg", ".png", ".webp"):
                path = resource_path(f"data/pictures/{picture_id}{ext}")
                if path.exists():
                    found = path
                    break
        _picture_files[picture_id] = found
    return _picture_files[picture_id]


@lru_cache(maxsize=256)
def picture_aspect(picture_id):
    """Width / height the picture's card should have: the photo's own shape,
    kept within sensible limits so a panorama or a tall tower still fits."""
    path = picture_path(picture_id)
    if path is None:
        return 4 / 3
    try:
        w, h = pygame.image.load(str(path)).get_size()
    except (pygame.error, OSError):
        return 4 / 3
    return max(0.62, min(1.6, w / h))


@lru_cache(maxsize=24)
def picture(picture_id, width, height):
    """The picture cropped to fill width x height, with rounded corners.
    Returns None when there is no such picture."""
    path = picture_path(picture_id)
    if path is None:
        return None
    try:
        image = pygame.image.load(str(path)).convert()
    except (pygame.error, OSError):
        return None
    scale = max(width / image.get_width(), height / image.get_height())
    size = (max(width, round(image.get_width() * scale)), max(height, round(image.get_height() * scale)))
    image = pygame.transform.smoothscale(image, size)
    out = pygame.Surface((width, height), pygame.SRCALPHA)
    # Keep a little more of the top than the bottom: heads and towers are up there.
    out.blit(image, (-(size[0] - width) // 2, -int((size[1] - height) * 0.35)))
    mask = pygame.Surface((width * 2, height * 2), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=int(min(width, height) * 0.18))
    out.blit(pygame.transform.smoothscale(mask, (width, height)), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


@lru_cache(maxsize=8)
def pin(size, color=(235, 70, 80)):
    """A map pin whose tip is at the bottom centre of the returned surface."""
    size = max(16, int(size))
    w, h = size * SS, int(size * 1.4) * SS
    big = pygame.Surface((w, h), pygame.SRCALPHA)
    big.fill((255, 255, 255, 0))
    r = w * 0.40
    cx, cy = w / 2, r + w * 0.08
    for colour, grow in ((WHITE, w * 0.08), (color, 0)):
        pygame.draw.circle(big, colour, (cx, cy), r + grow)
        pygame.draw.polygon(big, colour, [(cx - (r + grow) * 0.86, cy + r * 0.52), (cx + (r + grow) * 0.86, cy + r * 0.52),
                                          (cx, h - (0 if grow else w * 0.10))])
    pygame.draw.circle(big, WHITE, (cx, cy), r * 0.42)
    return pygame.transform.smoothscale(big, (w // SS, h // SS))
