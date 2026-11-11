"""Equirectangular projection with zoom and pan. Pure maths, no pygame.

World coordinates are (lon, lat) degrees; screen coordinates are pixels.
Because the projection is linear, a distance in pixels converts to degrees
by a single division, which keeps the click tolerance simple.
"""
from __future__ import annotations

LON_MIN, LON_MAX = -180.0, 180.0
LAT_MIN, LAT_MAX = -90.0, 84.0  # nothing but ice above 84 N
MAX_ZOOM = 16.0


class Viewport:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height
        # Zoom 1 shows the whole world.
        self.base_scale = min(width / (LON_MAX - LON_MIN), height / (LAT_MAX - LAT_MIN))
        self.version = 0  # bumped on every change so renderers know to redraw
        self.reset()

    def reset(self):
        self.zoom = 1.0
        self.center_lon = (LON_MIN + LON_MAX) / 2
        self.center_lat = (LAT_MIN + LAT_MAX) / 2
        self.version += 1

    @property
    def scale(self):
        """Pixels per degree."""
        return self.base_scale * self.zoom

    @property
    def is_default(self):
        return self.zoom == 1.0

    def to_screen(self, lon, lat):
        s = self.scale
        return (self.x + self.width / 2 + (lon - self.center_lon) * s,
                self.y + self.height / 2 - (lat - self.center_lat) * s)

    def to_world(self, sx, sy):
        s = self.scale
        return (self.center_lon + (sx - self.x - self.width / 2) / s,
                self.center_lat - (sy - self.y - self.height / 2) / s)

    def px_to_deg(self, pixels):
        return pixels / self.scale

    def visible_box(self):
        """(lon_min, lat_min, lon_max, lat_max) currently on screen."""
        lon0, lat1 = self.to_world(self.x, self.y)
        lon1, lat0 = self.to_world(self.x + self.width, self.y + self.height)
        return (lon0, lat0, lon1, lat1)

    def contains_screen_point(self, sx, sy):
        return self.x <= sx < self.x + self.width and self.y <= sy < self.y + self.height

    def pan(self, dx_pixels, dy_pixels):
        """Move the map with the mouse (drag right -> map follows right)."""
        self.center_lon -= dx_pixels / self.scale
        self.center_lat += dy_pixels / self.scale
        self._clamp()
        self.version += 1

    def zoom_at(self, sx, sy, factor):
        """Zoom keeping the world point under the cursor in place."""
        lon, lat = self.to_world(sx, sy)
        self.zoom = max(1.0, min(MAX_ZOOM, self.zoom * factor))
        if self.zoom < 1.02:
            self.zoom = 1.0
        s = self.scale
        self.center_lon = lon - (sx - self.x - self.width / 2) / s
        self.center_lat = lat + (sy - self.y - self.height / 2) / s
        self._clamp()
        self.version += 1

    def _clamp(self):
        """Never show empty space beyond the edge of the world if avoidable."""
        s = self.scale
        half_w = self.width / 2 / s
        half_h = self.height / 2 / s
        self.center_lon = _clamp_axis(self.center_lon, half_w, LON_MIN, LON_MAX)
        self.center_lat = _clamp_axis(self.center_lat, half_h, LAT_MIN, LAT_MAX)


def _clamp_axis(center, half, low, high):
    if 2 * half >= high - low:
        return (low + high) / 2
    return max(low + half, min(high - half, center))
