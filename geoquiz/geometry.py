"""Pure geometry helpers. No pygame, no file access.

Coordinates are (longitude, latitude) in degrees. A *ring* is a list of
(lon, lat) tuples (implicitly closed), a *polygon* is a list of rings where
the first is the outline and the rest are holes, and a *path* is an open list
of points (used for rivers).
"""
from __future__ import annotations

import math

KM_PER_DEGREE = 111.195  # length of one degree of latitude


def bbox_of(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def merge_bboxes(boxes):
    boxes = list(boxes)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def bbox_contains(box, x, y, margin=0.0):
    return (box[0] - margin <= x <= box[2] + margin
            and box[1] - margin <= y <= box[3] + margin)


def point_in_ring(ring, x, y):
    """Even-odd ray casting test for one closed ring."""
    inside = False
    xj, yj = ring[-1]
    for xi, yi in ring:
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        xj, yj = xi, yi
    return inside


def point_in_polygon(polygon, x, y):
    """True if the point is inside the outline and not inside a hole."""
    if not point_in_ring(polygon[0], x, y):
        return False
    for hole in polygon[1:]:
        if point_in_ring(hole, x, y):
            return False
    return True


def _dist2_point_segment(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        t = 0.0
    else:
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    ex = ax + t * dx - px
    ey = ay + t * dy - py
    return ex * ex + ey * ey


def distance_to_path(points, x, y, closed=False):
    """Planar distance (in degrees) from a point to a polyline or ring edge."""
    if not points:
        return math.inf
    if len(points) == 1:
        return math.hypot(points[0][0] - x, points[0][1] - y)
    best = math.inf
    if closed:
        ax, ay = points[-1]
        rest = points
    else:
        ax, ay = points[0]
        rest = points[1:]
    for bx, by in rest:
        d = _dist2_point_segment(x, y, ax, ay, bx, by)
        if d < best:
            best = d
        ax, ay = bx, by
    return math.sqrt(best)


def _wrap180(d):
    return (d + 180.0) % 360.0 - 180.0


def km_to_path(points, lon, lat, closed=False):
    """Approximate ground distance in km from (lon, lat) to a polyline/ring.

    Each vertex is projected onto a plane around the query point, scaling
    longitude by the cosine of the mean latitude. Good to a few percent for
    distances up to a couple of thousand km, which is all the game needs.
    """
    if not points:
        return math.inf
    rad = math.pi / 360.0  # half-angle: mean latitude in radians

    if len(points) == 1:
        p = points[0]
        x = _wrap180(p[0] - lon) * math.cos((p[1] + lat) * rad)
        return math.hypot(x, p[1] - lat) * KM_PER_DEGREE

    # Each segment is placed on its own: its first end takes the short way
    # round to the query point and its second end continues from the first.
    # (Wrapping both ends independently would make a segment on the far side
    # of the globe, one end at +180 and the other at -180, appear to pass
    # straight through the query point; unwrapping along the whole path
    # instead would break for shapes that circle the globe, such as the
    # Southern Ocean.)
    if closed:
        prev = points[-1]
        rest = points
    else:
        prev = points[0]
        rest = points[1:]
    prev_cos = math.cos((prev[1] + lat) * rad)
    best = math.inf
    for p in rest:
        p_cos = math.cos((p[1] + lat) * rad)
        dlon_a = _wrap180(prev[0] - lon)
        dlon_b = dlon_a + _wrap180(p[0] - prev[0])
        d = _dist2_point_segment(0.0, 0.0, dlon_a * prev_cos, prev[1] - lat,
                                 dlon_b * p_cos, p[1] - lat)
        if d < best:
            best = d
        prev = p
        prev_cos = p_cos
    return math.sqrt(best) * KM_PER_DEGREE


def haversine_km(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def ring_area(ring):
    """Unsigned shoelace area in square degrees."""
    total = 0.0
    xj, yj = ring[-1]
    for xi, yi in ring:
        total += xj * yi - xi * yj
        xj, yj = xi, yi
    return abs(total) / 2.0


def ring_centroid(ring):
    n = len(ring)
    return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)


def simplify(points, tolerance):
    """Douglas-Peucker simplification of an open polyline (iterative)."""
    n = len(points)
    if n < 3:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance * tolerance
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = points[a]
        bx, by = points[b]
        worst = -1.0
        index = -1
        for i in range(a + 1, b):
            d = _dist2_point_segment(points[i][0], points[i][1], ax, ay, bx, by)
            if d > worst:
                worst = d
                index = i
        if worst > tol2:
            keep[index] = True
            stack.append((a, index))
            stack.append((index, b))
    return [p for p, k in zip(points, keep) if k]


def simplify_ring(ring, tolerance):
    """Simplify a closed ring; returns None if it collapses to nothing."""
    if len(ring) < 8:
        return list(ring)
    # Split at the point farthest from the first so both halves are open lines.
    x0, y0 = ring[0]
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - x0) ** 2 + (ring[i][1] - y0) ** 2)
    first = simplify(ring[: far + 1], tolerance)
    second = simplify(ring[far:] + [ring[0]], tolerance)
    out = first[:-1] + second[:-1]
    return out if len(out) >= 3 else None
