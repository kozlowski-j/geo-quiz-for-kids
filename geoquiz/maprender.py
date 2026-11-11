"""Draws the world map with pygame. Part of the UI layer.

The base map (ocean, countries, lakes, rivers) is rendered into a cached
surface that is only rebuilt when the viewport changes. While the view is
moving it is drawn quickly at screen resolution; a moment after it settles
it is redrawn at twice the size and scaled down, which smooths every edge
(on very large screens the redraw stays at screen size: see MAX_SMOOTH_HEIGHT).
Highlights (hover, correct-answer flash, hint) are drawn on top each frame.
"""
from __future__ import annotations

import time

import pygame

from .gfx import vertical_gradient

OCEAN_TOP = (178, 224, 247)
OCEAN_BOTTOM = (146, 205, 240)
LAND_SHADOW = (118, 180, 222)  # soft drop shadow under the land
LAKE = (168, 218, 246)
RIVER = (120, 190, 236)
LAND = (255, 255, 255)         # every country is plain white
BORDER = (168, 184, 204)       # soft grey-blue lines between countries and along coasts
HOVER_FILL = (214, 232, 255)   # the country under the cursor
HOVER_EDGE = (74, 137, 255)

DETAIL_SCALE = 16.0    # pixels per degree above which full-detail shapes are drawn
SETTLE_SECONDS = 0.12  # how long the view must rest before the smooth redraw
HQ = 2                 # supersampling factor of the smooth redraw
# Above this map height (4K screens) the smooth redraw is not supersampled:
# the buffer would be around 100 MB and slow to fill, and the pixels are
# small enough for the edges to look clean anyway.
MAX_SMOOTH_HEIGHT = 1500


def cull_ring(ring, view):
    """Drop vertices that cannot affect what is visible.

    A vertex is removed when it, the last vertex kept before it and the
    vertex after it all lie beyond the same edge of the view: the shortcut
    edge then stays beyond that edge too, so the visible part of the polygon
    is unchanged. (Comparing with the last *kept* vertex matters: with the
    original neighbour, two vertices dropped in a row against different
    edges would leave a shortcut that cuts across a corner of the view.)
    This makes drawing a huge country at high zoom several times faster.
    """
    x0, y0, x1, y1 = view
    codes = [(1 if x < x0 else 2 if x > x1 else 0) | (4 if y < y0 else 8 if y > y1 else 0)
             for x, y in ring]
    n = len(ring)
    out = []
    prev = codes[-1]
    for i in range(n):
        if prev & codes[i] & codes[(i + 1) % n]:
            continue
        out.append(ring[i])
        prev = codes[i]
    return out if len(out) >= 3 else None


class MapRenderer:
    def __init__(self, world, viewport):
        self.world = world
        self.vp = viewport
        self._cache = None
        self._cache_version = None
        self._big = None
        self._smooth_pending = False
        self._changed_at = 0.0
        self._overlay = None
        self._hq = HQ if viewport.height <= MAX_SMOOTH_HEIGHT else 1

    # ---- projection helpers ----------------------------------------------
    def _transform(self, local, k=1):
        """(scale, x offset, y offset) for lon/lat -> pixels (times k)."""
        vp = self.vp
        s = vp.scale
        ox = vp.width / 2 - vp.center_lon * s
        oy = vp.height / 2 + vp.center_lat * s
        if not local:
            ox += vp.x
            oy += vp.y
        return s * k, ox * k, oy * k

    @staticmethod
    def _visible(box, view):
        return not (box[2] < view[0] or box[0] > view[2] or box[3] < view[1] or box[1] > view[3])

    def _polys_for(self, area):
        """Polygons to draw at the current zoom, with their bounding boxes."""
        if area.kind == "country" and self.vp.scale < DETAIL_SCALE:
            return area.lo_polys, area.poly_boxes
        return area.polys, area.poly_boxes

    # ---- base map ----------------------------------------------------------
    def draw(self, screen, smooth_now=False):
        vp = self.vp
        size = (vp.width, vp.height)
        if self._cache is None or self._cache.get_size() != size:
            self._cache = pygame.Surface(size).convert()
            self._big = pygame.Surface((size[0] * self._hq, size[1] * self._hq)).convert()
            self._cache_version = None
        now = time.monotonic()
        if self._cache_version != vp.version:
            self._cache_version = vp.version
            self._changed_at = now
            if smooth_now:
                self._render_smooth()
            else:
                self._render(self._cache, 1, smooth=False)
                self._smooth_pending = True
        elif self._smooth_pending and (smooth_now or now - self._changed_at >= SETTLE_SECONDS):
            self._render_smooth()
        screen.blit(self._cache, (vp.x, vp.y))

    def _render_smooth(self):
        self._render(self._big, self._hq, smooth=True)
        if self._hq == 1:
            self._cache.blit(self._big, (0, 0))
        else:
            pygame.transform.smoothscale(self._big, self._cache.get_size(), self._cache)
        self._smooth_pending = False

    def _render(self, surf, k, smooth):
        vp = self.vp
        s, ox, oy = self._transform(local=True, k=k)
        view = vp.visible_box()
        surf.blit(vertical_gradient(surf.get_size(), OCEAN_TOP, OCEAN_BOTTOM), (0, 0))

        detailed = vp.scale >= DETAIL_SCALE
        m = 20 / vp.scale  # keep a 20 pixel margin so culled edges stay off screen
        margin_view = (view[0] - m, view[1] - m, view[2] + m, view[3] + m)
        border_width = k if vp.scale < 40 else 2 * k
        shadow = 3 * k if smooth else 0  # the drop shadow is skipped while moving

        shapes = []  # points of every visible piece, biggest country first
        dots = []
        for country in self.world.countries:
            if not self._visible(country.bbox, view):
                continue
            polys, boxes = self._polys_for(country)
            for index, (poly, box) in enumerate(zip(polys, boxes)):
                if not self._visible(box, view):
                    continue
                w = (box[2] - box[0]) * vp.scale
                h = (box[3] - box[1]) * vp.scale
                if w < 2.5 and h < 2.5:
                    if index == 0:  # a whole country smaller than a few pixels: show a dot
                        dots.append(((box[0] + box[2]) / 2 * s + ox, oy - (box[1] + box[3]) / 2 * s))
                    continue
                ring = poly[0]
                if detailed and len(ring) > 200:
                    ring = cull_ring(ring, margin_view)
                    if ring is None:
                        continue
                shapes.append([(x * s + ox, oy - y * s) for x, y in ring])

        if shadow:
            for pts in shapes:
                pygame.draw.polygon(surf, LAND_SHADOW, [(x, y + shadow) for x, y in pts])
        for pts in shapes:
            pygame.draw.polygon(surf, LAND, pts)
            pygame.draw.lines(surf, BORDER, True, pts, border_width)
        for center in dots:
            pygame.draw.circle(surf, BORDER, center, 3.5 * k)
            pygame.draw.circle(surf, LAND, center, 2.5 * k)

        for lake in self.world.lakes:
            if not self._visible(lake.bbox, view):
                continue
            for poly, box in zip(lake.polys, lake.poly_boxes):
                if (box[2] - box[0]) * vp.scale < 2 and (box[3] - box[1]) * vp.scale < 2:
                    continue
                pts = [(x * s + ox, oy - y * s) for x, y in poly[0]]
                pygame.draw.polygon(surf, LAKE, pts)

        max_rank = 1 if vp.scale < 8 else 2 if vp.scale < 20 else 4
        width, height = surf.get_size()
        for rank, lines in self.world.drawn_rivers:
            if rank > max_rank:
                continue
            line_width = (2 if (rank <= 1 or vp.scale >= 20) else 1) * k
            for line in lines:
                pts = [(x * s + ox, oy - y * s) for x, y in line]
                if any(-50 <= px <= width + 50 and -50 <= py <= height + 50 for px, py in pts):
                    pygame.draw.lines(surf, RIVER, False, pts, line_width)

    # ---- highlights ----------------------------------------------------------
    def _screen_shapes(self, area):
        """(polygons, lines) of an area in screen pixels, visible pieces only."""
        s, ox, oy = self._transform(local=False)
        view = self.vp.visible_box()
        polys_out, lines_out = [], []
        polys, boxes = self._polys_for(area)
        for poly, box in zip(polys, boxes):
            if self._visible(box, view):
                polys_out.append([(x * s + ox, oy - y * s) for x, y in poly[0]])
        for line, box in zip(area.lines, area.line_boxes):
            if self._visible(box, view):
                lines_out.append([(x * s + ox, oy - y * s) for x, y in line])
        return polys_out, lines_out

    def draw_hover(self, screen, area):
        """Brighten the country under the cursor (no name shown)."""
        vp = self.vp
        old_clip = screen.get_clip()
        screen.set_clip(pygame.Rect(vp.x, vp.y, vp.width, vp.height))
        polys, _ = self._screen_shapes(area)
        fill = HOVER_FILL
        for pts in polys:
            if len(pts) >= 3:
                pygame.draw.polygon(screen, fill, pts)
                pygame.draw.lines(screen, HOVER_EDGE, True, pts, 3)
                pygame.draw.aalines(screen, HOVER_EDGE, True, pts)
        screen.set_clip(old_clip)

    def draw_highlight(self, screen, areas, fill_rgba, outline_rgb, outline_width):
        """Translucent fill plus a thick outline over the given areas."""
        vp = self.vp
        if self._overlay is None or self._overlay.get_size() != (vp.width, vp.height):
            self._overlay = pygame.Surface((vp.width, vp.height), pygame.SRCALPHA)
        overlay = self._overlay
        overlay.fill((0, 0, 0, 0))
        outline = (*outline_rgb, 255)
        seen = set()
        for area in areas:
            polys, lines = self._screen_shapes(area)
            for pts in polys:
                key = (len(pts), pts[0])
                if key in seen or len(pts) < 3:
                    continue  # the same shape listed twice (country + island id)
                seen.add(key)
                local = [(x - vp.x, y - vp.y) for x, y in pts]
                pygame.draw.polygon(overlay, fill_rgba, local)
                pygame.draw.lines(overlay, outline, True, local, outline_width)
            for pts in lines:
                local = [(x - vp.x, y - vp.y) for x, y in pts]
                pygame.draw.lines(overlay, outline, False, local, outline_width + 3)
        screen.blit(overlay, (vp.x, vp.y))

    def main_screen_box(self, area):
        """Screen rectangle of the biggest piece of an area (may be off screen)."""
        box = area.main_box
        x0, y1 = self.vp.to_screen(box[0], box[1])
        x1, y0 = self.vp.to_screen(box[2], box[3])
        return pygame.Rect(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))
