"""Synthetic tests of the pure geometry helpers (no map data needed)."""
import math

import pytest

from geoquiz import geometry as geo

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]
HOLE = [(4, 4), (6, 4), (6, 6), (4, 6)]
DONUT = [SQUARE, HOLE]


# ---- bounding boxes ---------------------------------------------------------
def test_bbox_of_and_merge():
    assert geo.bbox_of([(1, 5), (-2, 7), (3, -1)]) == (-2, -1, 3, 7)
    assert geo.merge_bboxes([(0, 0, 1, 1), (-5, 2, 0.5, 9)]) == (-5, 0, 1, 9)


def test_bbox_contains_with_and_without_margin():
    box = (0, 0, 10, 10)
    assert geo.bbox_contains(box, 5, 5)
    assert geo.bbox_contains(box, 0, 10)  # edges are inclusive
    assert not geo.bbox_contains(box, 10.5, 5)
    assert geo.bbox_contains(box, 10.5, 5, margin=1)
    assert not geo.bbox_contains(box, 5, -1.5, margin=1)


# ---- point in ring / polygon ------------------------------------------------
@pytest.mark.parametrize("x, y, inside", [
    (5, 5, True),
    (0.01, 0.01, True),
    (9.99, 9.99, True),
    (-0.01, 5, False),
    (10.01, 5, False),
    (5, 10.01, False),
    (5, -0.01, False),
    (20, 20, False),
])
def test_point_in_ring_square(x, y, inside):
    assert geo.point_in_ring(SQUARE, x, y) is inside


def test_point_in_ring_does_not_depend_on_winding_or_start_vertex():
    reversed_square = SQUARE[::-1]
    rotated = SQUARE[2:] + SQUARE[:2]
    for ring in (reversed_square, rotated):
        assert geo.point_in_ring(ring, 5, 5)
        assert not geo.point_in_ring(ring, 11, 5)


def test_point_in_ring_concave_shape():
    # An "L": the notch (top right quarter) is outside although inside the bbox.
    ell = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
    assert geo.point_in_ring(ell, 2, 8)
    assert geo.point_in_ring(ell, 8, 2)
    assert not geo.point_in_ring(ell, 8, 8)


def test_point_in_ring_triangle_is_not_its_bounding_box():
    triangle = [(0, 0), (10, 0), (0, 10)]
    assert geo.point_in_ring(triangle, 2, 2)
    assert not geo.point_in_ring(triangle, 8, 8)


@pytest.mark.parametrize("x, y, inside", [
    (1, 1, True),      # in the outline, outside the hole
    (5, 5, False),     # in the hole
    (4.5, 5.5, False),
    (3.9, 5, True),    # just beside the hole
    (6.1, 5, True),
    (12, 5, False),    # outside everything
])
def test_point_in_polygon_respects_holes(x, y, inside):
    assert geo.point_in_polygon(DONUT, x, y) is inside


def test_point_in_polygon_without_holes():
    assert geo.point_in_polygon([SQUARE], 5, 5)
    assert not geo.point_in_polygon([SQUARE], -1, 5)


# ---- planar distance --------------------------------------------------------
def test_distance_to_path_open_polyline():
    line = [(0, 0), (10, 0)]
    assert geo.distance_to_path(line, 5, 3) == pytest.approx(3)
    assert geo.distance_to_path(line, 5, 0) == pytest.approx(0)
    # Beyond the end the nearest point is the end vertex.
    assert geo.distance_to_path(line, 13, 4) == pytest.approx(5)
    assert geo.distance_to_path(line, -3, -4) == pytest.approx(5)


def test_distance_to_path_closed_uses_the_closing_edge():
    # The closing edge of the square runs from (0, 10) back to (0, 0).
    assert geo.distance_to_path(SQUARE, -2, 5, closed=True) == pytest.approx(2)
    # As an open path that edge is missing: nearest are the corners.
    assert geo.distance_to_path(SQUARE, -2, 5, closed=False) == pytest.approx(math.hypot(2, 5))


def test_distance_to_path_inside_a_ring_is_distance_to_the_edge():
    assert geo.distance_to_path(SQUARE, 5, 5, closed=True) == pytest.approx(5)
    assert geo.distance_to_path(SQUARE, 1, 5, closed=True) == pytest.approx(1)


def test_distance_to_path_degenerate_inputs():
    assert geo.distance_to_path([], 1, 1) == math.inf
    assert geo.distance_to_path([(1, 1)], 4, 5) == pytest.approx(5)
    # A zero-length segment must not divide by zero.
    assert geo.distance_to_path([(2, 2), (2, 2)], 2, 5) == pytest.approx(3)


# ---- ground distance --------------------------------------------------------
def test_haversine_known_distances():
    assert geo.haversine_km(0, 0, 0, 0) == 0
    # One degree of latitude.
    assert geo.haversine_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.2)
    # A quarter of the way around the equator.
    assert geo.haversine_km(0, 0, 90, 0) == pytest.approx(10007.5, rel=1e-3)
    # Paris - London is about 344 km.
    assert geo.haversine_km(2.35, 48.86, -0.13, 51.51) == pytest.approx(344, abs=5)


def test_haversine_is_symmetric():
    a = geo.haversine_km(2.35, 48.86, 37.62, 55.75)
    b = geo.haversine_km(37.62, 55.75, 2.35, 48.86)
    assert a == pytest.approx(b)
    assert a == pytest.approx(2487, abs=15)  # Paris - Moscow


@pytest.mark.parametrize("p, q", [
    ((0, 0), (5, 0)),
    ((0, 0), (0, 9)),
    ((2.35, 48.86), (13.4, 52.52)),     # Paris - Berlin, ~880 km
    ((2.35, 48.86), (-3.7, 40.42)),     # Paris - Madrid, ~1050 km
    ((31.2, 30.0), (32.5, 15.6)),       # Cairo - Khartoum, ~1600 km
    ((-74.0, 40.7), (-87.6, 41.9)),     # New York - Chicago, ~1150 km
    ((151.2, -33.9), (144.96, -37.8)),  # Sydney - Melbourne, ~710 km
    ((10.75, 59.9), (24.94, 60.17)),    # Oslo - Helsinki at 60 N, ~790 km
    ((18.0, 59.3), (25.7, 71.2)),       # Stockholm - North Cape, ~1370 km
])
def test_km_to_path_single_point_agrees_with_haversine(p, q):
    expected = geo.haversine_km(p[0], p[1], q[0], q[1])
    assert geo.km_to_path([q], p[0], p[1]) == pytest.approx(expected, rel=0.03)


def test_km_to_path_to_a_segment_and_a_ring():
    # 3 degrees of latitude north of a segment lying on the equator.
    assert geo.km_to_path([(-5, 0), (5, 0)], 0, 3) == pytest.approx(3 * 111.195, rel=0.01)
    # 2 degrees of longitude east of a square, at the equator.
    square = [(0, -2), (4, -2), (4, 2), (0, 2)]
    assert geo.km_to_path(square, 6, 0, closed=True) == pytest.approx(2 * 111.195, rel=0.01)
    # West of the square the nearest edge is the closing one.
    assert geo.km_to_path(square, -2, 0, closed=True) == pytest.approx(2 * 111.195, rel=0.01)
    assert geo.km_to_path(square, -2, 0, closed=False) > 2.5 * 111.195


def test_km_to_path_shrinks_longitude_with_latitude():
    # One degree of longitude at 60 N is half as long as at the equator.
    at_equator = geo.km_to_path([(1, 0)], 0, 0)
    at_sixty = geo.km_to_path([(1, 60)], 0, 60)
    assert at_sixty == pytest.approx(at_equator / 2, rel=0.01)


def test_km_to_path_empty_is_infinite():
    assert geo.km_to_path([], 0, 0) == math.inf


def test_km_to_path_wraps_across_the_antimeridian():
    # 179 E and 179 W are two degrees apart, not 358.
    expected = geo.haversine_km(179, 0, -179, 0)
    assert expected == pytest.approx(222.4, abs=1)
    assert geo.km_to_path([(-179, 0)], 179, 0) == pytest.approx(expected, rel=0.02)
    assert geo.km_to_path([(179, 0)], -179, 0) == pytest.approx(expected, rel=0.02)


def test_km_to_path_segment_across_the_antimeridian():
    # A short path east of the date line, seen from just west of it.
    path = [(-179, -5), (-179, 5)]
    assert geo.km_to_path(path, 179, 0) == pytest.approx(222.4, rel=0.02)


def test_km_to_path_is_large_for_a_shape_on_the_far_side_of_the_globe():
    # A France-sized line around the Greenwich meridian, seen from the middle
    # of the North Pacific at the same latitude: about 9000 km away. The two
    # ends unwrap to opposite sides of the query point, but the path does not
    # pass anywhere near it.
    path = [(-5, 47), (8, 47)]
    true_km = min(geo.haversine_km(179, 47, x, y) for x, y in path)
    assert true_km > 8000
    assert geo.km_to_path(path, 179, 47) > 3000


# ---- area / centroid --------------------------------------------------------
def test_ring_area():
    assert geo.ring_area(SQUARE) == pytest.approx(100)
    assert geo.ring_area(SQUARE[::-1]) == pytest.approx(100)  # unsigned
    assert geo.ring_area([(0, 0), (10, 0), (0, 10)]) == pytest.approx(50)
    assert geo.ring_area([(0, 0), (5, 5), (10, 10)]) == pytest.approx(0)


def test_ring_centroid_of_square():
    assert geo.ring_centroid(SQUARE) == pytest.approx((5, 5))


# ---- simplification ---------------------------------------------------------
def test_simplify_drops_collinear_points_and_keeps_the_ends():
    line = [(x, 0) for x in range(11)]
    assert geo.simplify(line, 0.1) == [(0, 0), (10, 0)]


def test_simplify_keeps_points_that_stick_out_more_than_the_tolerance():
    line = [(0, 0), (5, 3), (10, 0)]
    assert geo.simplify(line, 1) == line
    assert geo.simplify(line, 5) == [(0, 0), (10, 0)]


def test_simplify_keeps_a_corner_and_drops_the_noise():
    line = [(0, 0), (2, 0.01), (5, 0), (5, 2.5), (5.01, 4), (5, 5)]
    assert geo.simplify(line, 0.1) == [(0, 0), (5, 0), (5, 5)]


def test_simplify_short_inputs_are_returned_as_a_copy():
    two = [(0, 0), (1, 1)]
    out = geo.simplify(two, 10)
    assert out == two and out is not two
    assert geo.simplify([], 1) == []


def test_simplify_result_is_an_ordered_subset():
    line = [(i, math.sin(i / 3.0) * 4) for i in range(60)]
    out = geo.simplify(line, 0.5)
    assert out[0] == line[0] and out[-1] == line[-1]
    assert 2 < len(out) < len(line)
    positions = [line.index(p) for p in out]
    assert positions == sorted(positions)
    # Every dropped point stays within the tolerance of the simplified line.
    for x, y in line:
        assert geo.distance_to_path(out, x, y) <= 0.5 + 1e-9


def _circle(n, radius=10.0):
    return [(radius * math.cos(2 * math.pi * i / n), radius * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def test_simplify_ring_reduces_points_but_keeps_the_shape():
    ring = _circle(200)
    out = geo.simplify_ring(ring, 0.05)
    assert 8 <= len(out) < len(ring)
    assert set(out) <= set(ring)
    assert len(set(out)) == len(out)  # the closing point is not duplicated
    assert geo.ring_area(out) == pytest.approx(geo.ring_area(ring), rel=0.03)
    assert geo.point_in_ring(out, 0, 0)
    assert not geo.point_in_ring(out, 10.5, 0)


def test_simplify_ring_square_with_extra_points_becomes_four_corners():
    ring = ([(x, 0) for x in range(10)] + [(10, y) for y in range(10)]
            + [(x, 10) for x in range(10, 0, -1)] + [(0, y) for y in range(10, 0, -1)])
    out = geo.simplify_ring(ring, 0.01)
    assert sorted(out) == sorted([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert geo.ring_area(out) == pytest.approx(100)


def test_simplify_ring_leaves_tiny_rings_alone():
    ring = [(0, 0), (1, 0), (1, 1), (0.5, 1.5), (0, 1)]
    out = geo.simplify_ring(ring, 100)
    assert out == ring and out is not ring


def test_simplify_ring_returns_none_when_it_collapses():
    # A sliver much thinner than the tolerance.
    sliver = [(x, 0.0) for x in range(6)] + [(x, 0.001) for x in range(5, -1, -1)]
    assert geo.simplify_ring(sliver, 0.5) is None
