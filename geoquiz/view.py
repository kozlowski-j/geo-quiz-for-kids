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
        # Bumped whenever the view really changes, so renderers know to redraw
        # (and a "drag" that could not move the map can be told from one that did).
        self.version = 0
        self.zoom = 1.0
        self.center_lon = (LON_MIN + LON_MAX) / 2
        self.center_lat = (LAT_MIN + LAT_MAX) / 2

    def _set(self, zoom, center_lon, center_lat):
        """Apply a new view, keeping it inside the world."""
        scale = self.base_scale * zoom
        center_lon = _clamp_axis(center_lon, self.width / 2 / scale, LON_MIN, LON_MAX)
        center_lat = _clamp_axis(center_lat, self.height / 2 / scale, LAT_MIN, LAT_MAX)
        if (zoom, center_lon, center_lat) != (self.zoom, self.center_lon, self.center_lat):
            self.zoom, self.center_lon, self.center_lat = zoom, center_lon, center_lat
            self.version += 1

    def reset(self):
        self._set(1.0, (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2)

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

    def visible_box(self):
        """(lon_min, lat_min, lon_max, lat_max) currently on screen."""
        lon0, lat1 = self.to_world(self.x, self.y)
        lon1, lat0 = self.to_world(self.x + self.width, self.y + self.height)
        return (lon0, lat0, lon1, lat1)

    def contains_screen_point(self, sx, sy):
        return self.x <= sx < self.x + self.width and self.y <= sy < self.y + self.height

    def pan(self, dx_pixels, dy_pixels):
        """Move the map with the mouse (drag right -> map follows right).
        Never shows empty space beyond the edge of the world if avoidable."""
        s = self.scale
        self._set(self.zoom, self.center_lon - dx_pixels / s, self.center_lat + dy_pixels / s)

    def zoom_at(self, sx, sy, factor):
        """Zoom keeping the world point under the cursor in place."""
        lon, lat = self.to_world(sx, sy)
        zoom = max(1.0, min(MAX_ZOOM, self.zoom * factor))
        if zoom < 1.02:
            zoom = 1.0
        s = self.base_scale * zoom
        self._set(zoom, lon - (sx - self.x - self.width / 2) / s,
                  lat + (sy - self.y - self.height / 2) / s)


def _clamp_axis(center, half, low, high):
    if 2 * half >= high - low:
        return (low + high) / 2
    return max(low + half, min(high - half, center))
