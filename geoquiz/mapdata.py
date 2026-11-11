"""Loads the bundled Natural Earth data and answers geometry questions.

Everything clickable is an ``Area`` with an id of the form ``kind:Name``:

    country:France        continent:Africa      ocean:Pacific Ocean
    sea:Mediterranean Sea region:Sahara         river:Nile
    lake:Lake Victoria

Ids are matched case-insensitively. No pygame in this module.
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

from . import geometry as geo
from .paths import resource_path

WORLD_FILE = "data/map/world.json.gz"
CLOSE_KM = 1000.0
KINDS = ("country", "continent", "ocean", "sea", "region", "river", "lake")


def _ring(flat):
    return list(zip(flat[0::2], flat[1::2]))


def _polys(flat_polys):
    return [[_ring(r) for r in poly] for poly in flat_polys]


class Area:
    """A named, clickable thing on the map: polygons and/or lines."""

    def __init__(self, kind, name, polys=(), lines=(), lo_polys=None, color=0, cls=""):
        self.kind = kind
        self.name = name
        self.id = f"{kind}:{name}"
        self.polys = list(polys)
        self.lines = list(lines)
        self.lo_polys = lo_polys if lo_polys is not None else self.polys
        self.color = color
        self.cls = cls
        self.neighbors = set()  # ids of bordering countries
        self.continent = ""
        self.poly_boxes = [geo.bbox_of(p[0]) for p in self.polys]
        self.line_boxes = [geo.bbox_of(l) for l in self.lines]
        boxes = self.poly_boxes + self.line_boxes
        self.bbox = geo.merge_bboxes(boxes) if boxes else (0.0, 0.0, 0.0, 0.0)
        # Size of the biggest piece, as the side of a square with the same
        # area (degrees). Used to decide what is too small for the easy level.
        self.main_box = self.bbox  # bounding box of the biggest piece
        if self.polys:
            areas = [geo.ring_area(p[0]) for p in self.polys]
            biggest = max(range(len(areas)), key=areas.__getitem__)
            self.size_deg = math.sqrt(areas[biggest])
            self.main_box = self.poly_boxes[biggest]
        elif self.lines:
            self.size_deg = max(max(b[2] - b[0], b[3] - b[1]) for b in self.line_boxes)
        else:
            self.size_deg = 0.0

    def __repr__(self):
        return f"<Area {self.id}>"

    def contains(self, lon, lat):
        """Exact point-in-polygon test on the real shape (holes respected)."""
        if not self.polys or not geo.bbox_contains(self.bbox, lon, lat):
            return False
        for poly, box in zip(self.polys, self.poly_boxes):
            if geo.bbox_contains(box, lon, lat) and geo.point_in_polygon(poly, lon, lat):
                return True
        return False

    def distance_deg(self, lon, lat, limit=math.inf):
        """Distance in map degrees to the shape; 0 inside. Pieces farther than
        ``limit`` are skipped (the result is then > limit or inf)."""
        if self.contains(lon, lat):
            return 0.0
        best = math.inf
        for poly, box in zip(self.polys, self.poly_boxes):
            if geo.bbox_contains(box, lon, lat, min(limit, best)):
                for ring in poly:
                    d = geo.distance_to_path(ring, lon, lat, closed=True)
                    if d < best:
                        best = d
        for line, box in zip(self.lines, self.line_boxes):
            if geo.bbox_contains(box, lon, lat, min(limit, best)):
                d = geo.distance_to_path(line, lon, lat)
                if d < best:
                    best = d
        return best

    def hit(self, lon, lat, tolerance_deg=0.0):
        """True if the point is inside the shape or within the tolerance of it."""
        if self.contains(lon, lat):
            return True
        if tolerance_deg <= 0:
            return False
        return self.distance_deg(lon, lat, tolerance_deg) <= tolerance_deg

    def distance_km(self, lon, lat, limit=math.inf):
        """Approximate ground distance in km; 0 inside. Pieces that are
        certainly farther than ``limit`` are skipped."""
        if self.contains(lon, lat):
            return 0.0
        best = math.inf
        shapes = [(p[0], b, True) for p, b in zip(self.polys, self.poly_boxes)]
        shapes += [(l, b, False) for l, b in zip(self.lines, self.line_boxes)]
        for points, box, closed in shapes:
            if _box_gap_km(box, lon, lat) > min(limit, best):
                continue
            d = geo.km_to_path(points, lon, lat, closed=closed)
            if d < best:
                best = d
        return best


def _box_gap_km(box, lon, lat):
    """Lower bound on the distance from a point to anything inside a box."""
    gap_lat = max(box[1] - lat, lat - box[3], 0.0)
    if box[0] <= lon <= box[2]:
        gap_lon = 0.0
    else:
        gap_lon = min(abs(geo._wrap180(box[0] - lon)), abs(geo._wrap180(box[2] - lon)))
    widest = max(abs(lat), abs(box[1]), abs(box[3]))
    gap_lon *= math.cos(math.radians(min(widest, 89.0)))
    return max(gap_lat, gap_lon) * geo.KM_PER_DEGREE


class WorldMap:
    def __init__(self, data):
        self.areas = {}      # lower-case id -> Area
        self.countries = []  # biggest first, so enclaves are drawn on top
        self.seas = []
        self.lakes = []
        self.drawn_rivers = []  # (rank, [line, ...]) for decoration

        for c in data["countries"]:
            area = Area("country", c["name"], _polys(c["polys"]), lo_polys=_polys(c["lo"]),
                        color=c["color"])
            area.continent = c["continent"]
            area.neighbors = {f"country:{n}" for n in c["neighbors"]}
            self._add(area)
            self.areas[f"country:{c['a3']}".lower()] = area  # alias, e.g. country:FRA
            self.countries.append(area)
        self.countries.sort(key=lambda a: -a.size_deg)

        for c in data["continents"]:
            self._add(Area("continent", c["name"], _polys(c["polys"])))
        for r in data["regions"]:
            self._add(Area("region", r["name"], _polys(r["polys"]), cls=r["class"]))

        ocean_polys = {o["name"]: [] for o in data["oceans"]}
        for part in data["ocean_parts"]:
            ocean_polys[part["ocean"]].extend(_polys(part["polys"]))
        for s in data["seas"]:
            polys = _polys(s["polys"])
            area = Area("sea", s["name"], polys, cls=s["class"])
            self._add(area)
            self.seas.append(area)
            if s["ocean"]:
                ocean_polys[s["ocean"]].extend(polys)
        self.oceans = []
        for name, polys in ocean_polys.items():
            area = Area("ocean", name, polys)
            self._add(area)
            self.oceans.append(area)

        for r in data["rivers"]:
            self._add(Area("river", r["name"], lines=[_ring(l) for l in r["lines"]]))
        for l in data["lakes"]:
            area = Area("lake", l["name"], _polys(l["polys"]))
            self._add(area)
            self.lakes.append(area)
        for r in data["drawn_rivers"]:
            self.drawn_rivers.append((r["rank"], [_ring(l) for l in r["lines"]]))

    def _add(self, area):
        self.areas[area.id.lower()] = area

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path else resource_path(WORLD_FILE)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return cls(json.load(fh))

    # ---- lookup -----------------------------------------------------------
    def find(self, ref):
        """Area for a reference like 'country:France', or None."""
        return self.areas.get(" ".join(str(ref).split()).lower())

    def resolve(self, ref):
        area = self.find(ref)
        if area is None:
            raise KeyError(f"unknown map area: {ref!r}")
        return area

    def all_ids(self):
        return sorted({a.id for a in self.areas.values()})

    # ---- what is under a point ---------------------------------------------
    def country_at(self, lon, lat):
        for c in self.countries:
            if c.contains(lon, lat):
                return c
        return None

    def water_at(self, lon, lat):
        """The sea or ocean under a point (smaller seas win over oceans)."""
        for s in self.seas:
            if s.contains(lon, lat):
                return s
        for o in self.oceans:
            if o.contains(lon, lat):
                return o
        return None

    def thing_at(self, lon, lat):
        """What a child would say they clicked: a country, else a sea/ocean."""
        return self.country_at(lon, lat) or self.water_at(lon, lat)

    # ---- game rules ----------------------------------------------------------
    def hit_any(self, targets, lon, lat, tolerance_deg=0.0):
        """The first target hit by the click, or None. Exact hits win over
        near misses so that a click inside one target is never ambiguous."""
        for t in targets:
            if t.contains(lon, lat):
                return t
        if tolerance_deg > 0:
            for t in targets:
                if t.hit(lon, lat, tolerance_deg):
                    return t
        return None

    def is_close(self, targets, lon, lat, clicked=None, close_km=CLOSE_KM):
        """A wrong click is 'close' if the clicked country borders a target
        country, or the click is within about ``close_km`` of any target."""
        if clicked is not None and clicked.kind == "country":
            for t in targets:
                if t.kind == "country" and clicked.id in t.neighbors:
                    return True
        for t in targets:
            if t.distance_km(lon, lat, close_km) <= close_km:
                return True
        return False
