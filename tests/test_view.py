"""Viewport: equirectangular projection with zoom and pan."""
import pytest

from geoquiz.view import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, MAX_ZOOM, Viewport

# 1920 x 928 has exactly the aspect of the map (360 x 174 degrees).
W, H = 1920, 928
POINTS = [(0.0, 0.0), (2.35, 48.86), (-155.5, 19.6), (179.0, -17.0), (-180.0, 84.0),
          (180.0, -90.0), (31.2, 30.0)]


@pytest.fixture
def view():
    return Viewport(0, 0, W, H)


def test_default_view_shows_the_whole_world(view):
    assert view.zoom == 1.0 and view.is_default
    assert view.scale == pytest.approx(1920 / 360)
    assert view.visible_box() == pytest.approx((LON_MIN, LAT_MIN, LON_MAX, LAT_MAX))


def test_corners_of_the_world_map_to_the_corners_of_the_screen(view):
    assert view.to_screen(LON_MIN, LAT_MAX) == pytest.approx((0, 0))
    assert view.to_screen(LON_MAX, LAT_MIN) == pytest.approx((W, H))
    assert view.to_screen(0, (LAT_MIN + LAT_MAX) / 2) == pytest.approx((W / 2, H / 2))


def test_north_is_up_and_east_is_right(view):
    x0, y0 = view.to_screen(0, 0)
    x1, y1 = view.to_screen(10, 10)
    assert x1 > x0 and y1 < y0


def test_base_scale_fits_the_narrower_dimension():
    wide = Viewport(0, 0, 4000, 870)        # height limits: 870 / 174 = 5
    assert wide.scale == pytest.approx(5.0)
    tall = Viewport(0, 0, 720, 3000)        # width limits: 720 / 360 = 2
    assert tall.scale == pytest.approx(2.0)


@pytest.mark.parametrize("lon, lat", POINTS)
def test_world_to_screen_round_trip(view, lon, lat):
    assert view.to_world(*view.to_screen(lon, lat)) == pytest.approx((lon, lat))


@pytest.mark.parametrize("lon, lat", POINTS)
def test_round_trip_when_zoomed_panned_and_offset(lon, lat):
    view = Viewport(40, 100, 1280, 700)
    view.zoom_at(500, 400, 3.7)
    view.pan(-130, 55)
    assert view.to_world(*view.to_screen(lon, lat)) == pytest.approx((lon, lat))
    sx, sy = 321.5, 456.25
    assert view.to_screen(*view.to_world(sx, sy)) == pytest.approx((sx, sy))


def test_viewport_offset_shifts_screen_coordinates():
    a = Viewport(0, 0, W, H)
    b = Viewport(100, 50, W, H)
    ax, ay = a.to_screen(2.35, 48.86)
    assert b.to_screen(2.35, 48.86) == pytest.approx((ax + 100, ay + 50))


def test_contains_screen_point():
    view = Viewport(100, 50, 800, 400)
    assert view.contains_screen_point(100, 50)
    assert view.contains_screen_point(899, 449)
    assert not view.contains_screen_point(900, 450)
    assert not view.contains_screen_point(99, 200)


def test_pixels_convert_to_degrees_by_the_scale(view):
    assert view.scale == pytest.approx(1920 / 360)
    view.zoom_at(W / 2, H / 2, 4)
    # 15 px apart on screen is 15 / scale degrees, which is what the click tolerance relies on.
    lon0, _ = view.to_world(700, 300)
    lon1, _ = view.to_world(715, 300)
    assert lon1 - lon0 == pytest.approx(15 / view.scale) == pytest.approx(2.8125 / 4)


@pytest.mark.parametrize("sx, sy", [(960, 464), (300, 200), (1500, 700), (10, 10), (1900, 900)])
@pytest.mark.parametrize("factor", [1.25, 2.0, 5.0])
def test_zoom_in_keeps_the_point_under_the_cursor_fixed(view, sx, sy, factor):
    before = view.to_world(sx, sy)
    view.zoom_at(sx, sy, factor)
    assert view.zoom == pytest.approx(factor)
    assert view.to_world(sx, sy) == pytest.approx(before)
    assert view.to_screen(*before) == pytest.approx((sx, sy))


def test_repeated_zoom_steps_keep_the_point_fixed(view):
    sx, sy = 1234, 321
    before = view.to_world(sx, sy)
    for _ in range(6):
        view.zoom_at(sx, sy, 1.25)
    assert view.zoom == pytest.approx(1.25 ** 6)
    assert view.to_world(sx, sy) == pytest.approx(before)


def test_zooming_in_and_back_out_at_the_same_point_keeps_it_fixed(view):
    sx, sy = 700, 300
    view.zoom_at(sx, sy, 8)
    before = view.to_world(sx, sy)
    view.zoom_at(sx, sy, 0.5)
    assert view.zoom == pytest.approx(4)
    assert view.to_world(sx, sy) == pytest.approx(before)


def test_zoom_changes_the_scale(view):
    view.zoom_at(W / 2, H / 2, 4)
    assert view.scale == pytest.approx(4 * 1920 / 360)
    assert not view.is_default
    box = view.visible_box()
    assert box[2] - box[0] == pytest.approx(90)
    assert box[3] - box[1] == pytest.approx(174 / 4)


def test_zoom_is_clamped_to_the_maximum(view):
    view.zoom_at(500, 400, 1000)
    assert view.zoom == MAX_ZOOM == 16.0
    view.zoom_at(500, 400, 2)
    assert view.zoom == MAX_ZOOM


def test_zoom_is_clamped_to_one(view):
    view.zoom_at(500, 400, 0.01)
    assert view.zoom == 1.0
    view.zoom_at(500, 400, 3)
    view.zoom_at(500, 400, 0.001)
    assert view.zoom == 1.0 and view.is_default
    assert view.visible_box() == pytest.approx((LON_MIN, LAT_MIN, LON_MAX, LAT_MAX))


def test_zoom_just_above_one_snaps_back_to_the_default(view):
    view.zoom_at(500, 400, 1.25)
    view.zoom_at(500, 400, 1.01 / 1.25)
    assert view.zoom == 1.0 and view.is_default


def test_zooming_out_never_shows_beyond_the_world(view):
    view.zoom_at(5, 5, 8)        # far into the top-left corner
    view.zoom_at(W - 5, H - 5, 0.25)
    lon0, lat0, lon1, lat1 = view.visible_box()
    assert lon0 >= LON_MIN - 1e-9 and lon1 <= LON_MAX + 1e-9
    assert lat0 >= LAT_MIN - 1e-9 and lat1 <= LAT_MAX + 1e-9


def test_pan_moves_the_map_with_the_mouse(view):
    view.zoom_at(W / 2, H / 2, 4)
    sx, sy = view.to_screen(10, 40)
    view.pan(50, -30)
    assert view.to_screen(10, 40) == pytest.approx((sx + 50, sy - 30))


def test_pan_at_default_zoom_cannot_move_the_world(view):
    view.pan(500, 300)
    view.pan(-2000, -900)
    assert view.visible_box() == pytest.approx((LON_MIN, LAT_MIN, LON_MAX, LAT_MAX))


@pytest.mark.parametrize("dx, dy, edge, limit", [
    (100000, 0, 0, LON_MIN),     # drag far right: stops at the west edge
    (-100000, 0, 2, LON_MAX),    # drag far left: stops at the east edge
    (0, 100000, 3, LAT_MAX),     # drag far down: stops at the north edge
    (0, -100000, 1, LAT_MIN),    # drag far up: stops at the south edge
])
def test_pan_is_clamped_at_the_edge_of_the_world(view, dx, dy, edge, limit):
    view.zoom_at(W / 2, H / 2, 4)
    view.pan(dx, dy)
    box = view.visible_box()
    assert box[edge] == pytest.approx(limit)
    assert box[0] >= LON_MIN - 1e-9 and box[2] <= LON_MAX + 1e-9
    assert box[1] >= LAT_MIN - 1e-9 and box[3] <= LAT_MAX + 1e-9
    assert box[2] - box[0] == pytest.approx(90)   # still the same zoom


def test_pan_into_a_corner_then_back(view):
    view.zoom_at(W / 2, H / 2, 2)
    view.pan(100000, 100000)
    assert view.to_world(0, 0) == pytest.approx((LON_MIN, LAT_MAX))
    view.pan(-96, 0)       # 96 px at zoom 2 is 9 degrees
    assert view.to_world(0, 0) == pytest.approx((LON_MIN + 9, LAT_MAX))


def test_reset_restores_the_default(view):
    view.zoom_at(300, 200, 6)
    view.pan(-400, 120)
    assert not view.is_default
    view.reset()
    assert view.zoom == 1.0 and view.is_default
    assert view.center_lon == 0 and view.center_lat == (LAT_MIN + LAT_MAX) / 2
    assert view.visible_box() == pytest.approx((LON_MIN, LAT_MIN, LON_MAX, LAT_MAX))
    assert view.scale == pytest.approx(1920 / 360)


def test_version_changes_on_every_change(view):
    seen = {view.version}
    for change in (lambda: view.zoom_at(10, 10, 2), lambda: view.pan(5, 5), view.reset):
        change()
        assert view.version not in seen
        seen.add(view.version)


def test_version_stays_put_when_nothing_moves(view):
    """The renderer redraws on a new version, and the UI uses it to tell a real
    drag from a shaky click, so a change that changes nothing must not count."""
    start = view.version
    view.reset()                      # already the whole world
    view.pan(40, -25)                 # at zoom 1 there is nowhere to go
    view.zoom_at(500, 300, 0.5)       # cannot zoom out past the whole world
    assert view.version == start
    view.zoom_at(500, 300, 2)
    assert view.version == start + 1
    view.reset()
    view.reset()
    assert view.version == start + 2


def test_letterboxed_view_keeps_the_world_centred():
    # Wider than the map: the world is centred with empty bars left and right.
    view = Viewport(0, 0, 2400, 870)
    assert view.scale == pytest.approx(5.0)
    assert view.to_screen(0, (LAT_MIN + LAT_MAX) / 2) == pytest.approx((1200, 435))
    assert view.to_screen(LON_MIN, LAT_MAX) == pytest.approx((300, 0))
    view.pan(1000, 0)
    assert view.to_screen(LON_MIN, LAT_MAX) == pytest.approx((300, 0))
