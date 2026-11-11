"""The pygame layer, run for real but without a screen or a sound card
(conftest.py selects SDL's dummy drivers). Each test gets a fresh App."""
import time

import pygame
import pytest

from geoquiz import gfx, ui
from geoquiz.maprender import cull_ring
from geoquiz.geometry import point_in_ring

FRANCE = (2.5, 47.0)


@pytest.fixture
def make_app(tmp_path):
    apps = []

    def make(size=(1920, 1080), sound=False):
        app = ui.App(fullscreen=False, speak=False, sound=sound, size=size,
                     progress_file=tmp_path / "progress.json", seed=1)
        apps.append(app)
        return app

    yield make
    for app in apps:
        app.close()


def frame(app):
    for event in pygame.event.get():
        app.handle_event(event)
    app.update(1 / 60)
    app.draw()


def find_france(app, zoom=1):
    task = next(t for t in app.tasks if t.targets == ["country:France"])
    app.start_round(task.difficulty, tasks=[task, task])
    if zoom > 1:
        app.viewport.zoom_at(*app.viewport.to_screen(*FRANCE), zoom)
    return tuple(int(v) for v in app.viewport.to_screen(*FRANCE))


def press_slide_release(app, start, dx):
    """A click during which the mouse slides ``dx`` pixels, as a small hand does."""
    end = (start[0] + dx, start[1])
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=start, rel=(0, 0), buttons=(0, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start, button=1))
    if dx:
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(dx, 0), buttons=(1, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1))
    frame(app)


# ---- clicks and drags ---------------------------------------------------------------------
@pytest.mark.parametrize("slide", [0, 5, 9, 12, 30])
def test_a_shaky_click_on_the_whole_world_view_still_answers(make_app, slide):
    """At zoom 1 the map cannot move, so a press that slides a little can only
    have been meant as a click. It used to be swallowed without a word."""
    app = make_app()
    press_slide_release(app, find_france(app), slide)
    assert app.phase == "celebrate"
    assert app.round.results[0] is True


def test_a_long_sweep_on_the_whole_world_view_is_not_an_answer(make_app):
    app = make_app()
    press_slide_release(app, find_france(app), int(app.H * 0.06))
    assert app.phase == "asking" and app.round.wrong_attempts == 0


def test_the_answer_is_where_the_button_went_down(make_app):
    app = make_app()
    start = find_france(app)
    slide = int(app.click_slop)
    released_over = app.world.country_at(*app.viewport.to_world(start[0] + slide, start[1]))
    assert released_over is not None and released_over.name != "France"   # slid into a neighbour
    press_slide_release(app, start, slide)
    assert app.phase == "celebrate"


@pytest.mark.parametrize("slide, answered", [(5, True), (12, True), (40, False)])
def test_zoomed_in_a_small_slide_is_a_click_and_a_big_one_pans(make_app, slide, answered):
    app = make_app()
    start = find_france(app, zoom=2)
    centre = (app.viewport.center_lon, app.viewport.center_lat)
    press_slide_release(app, start, slide)
    assert (app.phase == "celebrate") == answered
    assert ((app.viewport.center_lon, app.viewport.center_lat) != centre) == (not answered)
    assert app.round.wrong_attempts == 0


def test_drag_threshold_grows_with_the_screen(make_app):
    assert make_app((1280, 720)).drag_threshold < make_app((2560, 1440)).drag_threshold
    assert make_app((800, 600)).drag_threshold == 8


# ---- picture questions ----------------------------------------------------------------------
def test_shrinking_the_picture_builds_nothing_new(make_app):
    """Every frame of the shrink used to build a new shadowed panel and
    re-scale the photo from disk, which froze the game for half a second."""
    app = make_app()
    task = next(t for t in app.tasks if t.picture and gfx.picture_path(t.picture))
    app.start_round(task.difficulty, tasks=[task])
    frame(app)                                           # the big card is built here
    assert app.picture_intro_active
    sizes = set()
    built = (gfx.panel.cache_info().misses, gfx.picture.cache_info().misses)
    for step in range(1, 10):
        into_shrink = ui.PICTURE_SHRINK_SECONDS * step / 10
        app._picture_start = time.monotonic() - (ui.PICTURE_SECONDS - ui.PICTURE_SHRINK_SECONDS) - into_shrink
        rect, shrinking = app._picture_rect()
        assert shrinking
        sizes.add(rect.size)
        frame(app)
    assert len(sizes) == 9                               # it really animates...
    assert (gfx.panel.cache_info().misses, gfx.picture.cache_info().misses) == built  # ...for free
    app._picture_start = time.monotonic() - ui.PICTURE_SECONDS - 1
    assert app._picture_rect() == (app._thumb_rect(), False)
    frame(app)


def test_blur_of_a_big_shadow_is_done_small(make_app):
    make_app()
    surface = pygame.Surface((900, 700), pygame.SRCALPHA)
    pygame.draw.rect(surface, (20, 40, 80, 70), (60, 60, 780, 580), border_radius=40)
    start = time.perf_counter()
    blurred = gfx.soft_blur(surface, 18)
    assert time.perf_counter() - start < 0.25            # the plain blur took about half a second
    assert blurred.get_size() == surface.get_size()
    assert blurred.get_at((450, 350)).a == pytest.approx(70, abs=3)   # solid in the middle
    assert 15 < blurred.get_at((60, 350)).a < 55                      # soft at the edge
    assert blurred.get_at((5, 5)).a == 0


# ---- layout ---------------------------------------------------------------------------------
@pytest.mark.parametrize("size", [(1024, 768), (1280, 1024), (1920, 1080), (2560, 1440)])
@pytest.mark.parametrize("languages", [2, 3])
def test_bottom_row_of_the_menu_never_overlaps(make_app, size, languages):
    app = make_app(size)
    if languages == 3:                                   # a third strings.<code>.json was added
        app.languages = app.languages + ["xx"]
        app._build_buttons()
    row = [b.rect for b in app.language_buttons] + [app._collection_rect(), app.quit_button.rect]
    assert len(row) == languages + 2
    for left, right in zip(row, row[1:]):
        assert left.right < right.left
    assert app._collection_rect().width > 0
    screen = pygame.Rect(0, 0, *size)
    assert all(screen.contains(rect) for rect in row)
    frame(app)                                           # and it all draws


# ---- sound ----------------------------------------------------------------------------------
def test_chime_lasts_as_long_as_it_was_written(make_app):
    """A mono buffer on a stereo mixer plays at double speed, an octave up."""
    app = make_app(sound=True)
    if app.chime is None:
        pytest.skip("no audio device, not even a dummy one")
    assert pygame.mixer.get_init()[2] >= 1
    assert app.chime.get_length() == pytest.approx(0.67, abs=0.01)


# ---- map drawing ------------------------------------------------------------------------------
def test_culling_a_ring_never_changes_what_is_visible():
    """Two vertices dropped in a row against different edges of the view used
    to leave a shortcut across the corner, cutting a wedge out of the map."""
    view = (0.0, 0.0, 10.0, 10.0)
    # Passes the top-left corner on the outside: left of the view, then above it.
    ring = [(5, 5), (-2, 5), (-4, 8), (-3, 12), (2, 14), (5, 12)]
    culled = cull_ring(ring, view)
    assert culled is not None and len(culled) < len(ring)
    for x in range(0, 11):
        for y in range(0, 11):
            point = (x + 0.01, y + 0.013)
            if view[0] <= point[0] <= view[2] and view[1] <= point[1] <= view[3]:
                assert point_in_ring(culled, *point) == point_in_ring(ring, *point), point


def test_culling_drops_what_lies_wholly_beyond_one_edge():
    view = (0.0, 0.0, 10.0, 10.0)
    far_left = [(-30 + i % 5, i) for i in range(12)]
    assert cull_ring(far_left, view) is None
    square = [(2, 2), (8, 2), (8, 8), (2, 8)]
    assert cull_ring(square, view) == square
