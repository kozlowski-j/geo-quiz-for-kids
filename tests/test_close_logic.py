"""The "you are close" rule: neighbouring country, or within about 1000 km."""
import pytest

from conftest import haversine_km
from geoquiz import tasks as T
from geoquiz.mapdata import CLOSE_KM, Area

PARIS = (2.35, 48.86)
BERLIN = (13.4, 52.52)
MADRID = (-3.7, 40.42)
BRASILIA = (-47.9, -15.8)
CENTRAL_CHINA = (104.0, 32.0)        # Sichuan, about 2000 km from Russia
SOUTH_KAZAKHSTAN = (68.0, 43.0)      # about 1000 km from Russia
ATLANTIC_NEAR_FRANCE = (-10.0, 46.0)  # about 450 km west of Brittany
ATLANTIC_FAR = (-40.0, 45.0)          # about 2700 km west of Brittany
GULF_OF_ALASKA = (-140.0, 50.0)       # about 2500 km from the nearest bit of Russia


def areas(world, *refs):
    return [world.resolve(r) for r in refs]


def vertex_km(area, lon, lat):
    """Reference distance: nearest vertex of the shape by great circle."""
    points = [v for poly in area.polys for v in poly[0]] + [v for l in area.lines for v in l]
    return min(haversine_km(lon, lat, x, y) for x, y in points)


def round_for(world, *refs):
    task = T.Task("t", "country", "Find it.", list(refs), 2, areas(world, *refs))
    return T.Round(world, [task])


def test_default_threshold_is_1000_km():
    assert CLOSE_KM == 1000.0


# ---- neighbours -----------------------------------------------------------------
@pytest.mark.parametrize("country, neighbour", [
    ("France", "Germany"), ("France", "Spain"), ("France", "Belgium"), ("France", "Italy"),
    ("France", "Switzerland"), ("Russia", "China"), ("Russia", "Kazakhstan"),
    ("United States of America", "Canada"), ("United States of America", "Mexico"),
    ("South Africa", "Lesotho"),
])
def test_neighbours_are_recorded_both_ways(world, country, neighbour):
    a = world.find(f"country:{country}")
    b = world.find(f"country:{neighbour}")
    assert b.id in a.neighbors
    assert a.id in b.neighbors


def test_french_guiana_does_not_make_brazil_a_neighbour_of_france(world):
    france = world.find("country:France")
    brazil = world.find("country:Brazil")
    assert brazil.id not in france.neighbors
    assert france.id not in brazil.neighbors
    assert "country:Suriname" not in france.neighbors


@pytest.mark.parametrize("name", ["Poland", "Lithuania"])
def test_kaliningrad_makes_russia_a_neighbour(world, name):
    """An exclave next to a very wide mainland is still part of the country."""
    russia = world.find("country:Russia")
    other = world.find(f"country:{name}")
    assert other.id in russia.neighbors and russia.id in other.neighbors


def test_neighbour_ids_all_exist_and_never_include_the_country_itself(world):
    for country in world.countries:
        assert country.id not in country.neighbors
        for other in country.neighbors:
            assert world.find(other) is not None, (country.id, other)


def test_islands_have_no_neighbours(world):
    for name in ("Iceland", "Madagascar", "Malta", "Japan", "Australia"):
        assert world.find(f"country:{name}").neighbors == set(), name


@pytest.mark.parametrize("lon, lat, country", [(*BERLIN, "Germany"), (*MADRID, "Spain")])
def test_click_in_a_neighbour_of_france_is_close(world, lon, lat, country):
    clicked = world.country_at(lon, lat)
    assert clicked.id == f"country:{country}"
    assert world.is_close(areas(world, "country:France"), lon, lat, clicked)


@pytest.mark.parametrize("lon, lat, country", [
    (*CENTRAL_CHINA, "China"), (*SOUTH_KAZAKHSTAN, "Kazakhstan"),
])
def test_far_inside_a_big_neighbour_of_russia_is_still_close(world, lon, lat, country):
    russia = world.find("country:Russia")
    clicked = world.country_at(lon, lat)
    assert clicked.id == f"country:{country}"
    assert world.is_close([russia], lon, lat, clicked)


def test_border_rule_is_what_makes_central_china_close_to_russia(world):
    russia = world.find("country:Russia")
    china = world.find("country:China")
    assert russia.distance_km(*CENTRAL_CHINA) > 1500
    # By distance alone (no clicked country given) it would not be close.
    assert not world.is_close([russia], *CENTRAL_CHINA)
    assert world.is_close([russia], *CENTRAL_CHINA, china)


def test_border_rule_needs_the_clicked_country_to_border_the_target(world):
    russia = world.find("country:Russia")
    india = world.country_at(78.0, 20.0)
    assert india.id == "country:India"
    assert not world.is_close([russia], 78.0, 20.0, india)


def test_border_rule_only_applies_to_countries(world):
    # A sea passed as the clicked thing never counts as a neighbour.
    russia = world.find("country:Russia")
    sea = world.find("sea:Mediterranean Sea")
    assert not world.is_close([russia], 18.0, 35.0, sea)
    # A continent target has no neighbours: only the distance counts.
    africa = world.find("continent:Africa")
    china = world.find("country:China")
    assert not world.is_close([africa], *CENTRAL_CHINA, china)


def test_click_in_brazil_is_not_close_to_france(world):
    brazil = world.country_at(*BRASILIA)
    assert brazil.id == "country:Brazil"
    assert not world.is_close(areas(world, "country:France"), *BRASILIA, brazil)


# ---- distance rule ------------------------------------------------------------------
def test_ocean_click_500_km_from_the_target_is_close(world):
    france = world.find("country:France")
    assert world.country_at(*ATLANTIC_NEAR_FRANCE) is None
    assert 300 < france.distance_km(*ATLANTIC_NEAR_FRANCE) < 700
    assert world.is_close([france], *ATLANTIC_NEAR_FRANCE)


def test_ocean_click_3000_km_from_the_target_is_wrong(world):
    france = world.find("country:France")
    assert world.country_at(*ATLANTIC_FAR) is None
    assert 2200 < france.distance_km(*ATLANTIC_FAR) < 3300
    assert not world.is_close([france], *ATLANTIC_FAR)


def test_distance_is_zero_inside(world):
    assert world.find("country:France").distance_km(*PARIS) == 0.0
    assert world.find("country:France").distance_km(-53.0, 4.0) == 0.0   # French Guiana
    assert world.find("region:Sahara").distance_km(5.0, 23.0) == 0.0
    assert world.find("ocean:Atlantic Ocean").distance_km(-35.0, 30.0) == 0.0


@pytest.mark.parametrize("ref, lon, lat, low, high", [
    ("country:Germany", *PARIS, 230, 370),            # Paris - Saarland border, ~300 km
    ("country:United Kingdom", *PARIS, 200, 320),     # Paris - Sussex coast, ~250 km
    ("country:France", -0.1, 51.5, 100, 200),         # London - Calais coast, ~150 km
    ("country:France", *MADRID, 250, 420),            # Madrid - Pyrenees, ~330 km
    ("country:France", *BERLIN, 480, 680),            # Berlin - Alsace, ~570 km
    ("country:Ireland", -0.1, 51.5, 330, 480),        # London - Irish east coast, ~400 km
    ("country:Cuba", -80.2, 25.8, 250, 400),          # Miami - Cuba, ~330 km
    ("country:Sri Lanka", 77.6, 13.0, 380, 560),      # Bengaluru - Jaffna, ~450 km
])
def test_distance_km_against_known_distances(world, ref, lon, lat, low, high):
    assert low < world.find(ref).distance_km(lon, lat) < high


@pytest.mark.parametrize("ref, lon, lat", [
    ("country:Germany", *PARIS),
    ("country:France", *ATLANTIC_NEAR_FRANCE),
    ("country:France", *BERLIN),
    ("country:Iceland", -5.0, 58.0),         # north of Scotland
    ("country:Madagascar", 40.0, -5.0),      # off Tanzania
    ("country:New Zealand", 151.2, -33.9),   # Sydney, ~2000 km
    ("country:Japan", 116.4, 39.9),          # Beijing
    ("river:Nile", 20.0, 25.0),
    ("lake:Lake Victoria", 39.7, -4.0),      # Mombasa
])
def test_distance_km_agrees_with_great_circle_distance(world, ref, lon, lat):
    area = world.find(ref)
    assert area.distance_km(lon, lat) == pytest.approx(vertex_km(area, lon, lat), rel=0.06)


def test_threshold_can_be_changed(world):
    germany = areas(world, "country:Germany")
    # Paris is about 300 km from Germany.
    assert not world.is_close(germany, *PARIS, close_km=200)
    assert world.is_close(germany, *PARIS, close_km=400)
    france = areas(world, "country:France")
    assert world.is_close(france, *ATLANTIC_FAR, close_km=3500)


@pytest.mark.parametrize("lon, lat, close", [
    (-12.0, 47.0, True),     # ~550 km off Brittany
    (-16.0, 47.0, True),     # ~850 km
    (-21.0, 47.0, False),    # ~1250 km
    (-30.0, 45.0, False),    # ~2000 km
])
def test_threshold_is_about_1000_km(world, lon, lat, close):
    france = world.find("country:France")
    assert world.country_at(lon, lat) is None
    assert world.is_close([france], lon, lat) is close
    assert (vertex_km(france, lon, lat) <= 1000) is close


def test_distance_limit_only_skips_shapes_that_are_too_far(world):
    france = world.find("country:France")
    exact = france.distance_km(*ATLANTIC_NEAR_FRANCE)
    assert france.distance_km(*ATLANTIC_NEAR_FRANCE, 1000) == pytest.approx(exact)
    assert france.distance_km(*ATLANTIC_FAR, 1000) > 1000


def test_distance_counts_the_nearest_part_of_a_multi_part_country(world):
    # Off the coast of French Guiana: far from Paris, near France.
    france = world.find("country:France")
    assert world.country_at(-50.0, 7.0) is None
    assert france.distance_km(-50.0, 7.0) < 500
    assert world.is_close([france], -50.0, 7.0)


# ---- non-country targets ----------------------------------------------------------------
def test_river_target_uses_distance_only(world):
    nile = areas(world, "river:Nile")
    egypt = world.find("country:Egypt")
    libya = world.country_at(20.0, 25.0)
    assert libya.id == "country:Libya" and egypt.id in libya.neighbors
    # Western Egypt, a few hundred km from the river: close.
    assert world.is_close(nile, 27.0, 27.0, egypt)
    assert world.is_close(nile, 27.0, 27.0)
    # Eastern Libya is ~1100 km away; bordering Egypt does not help.
    assert nile[0].distance_km(20.0, 25.0) > 1000
    assert not world.is_close(nile, 20.0, 25.0, libya)
    assert not world.is_close(nile, *PARIS, world.find("country:France"))


def test_nile_distance_near_cairo_is_small(world):
    assert world.find("river:Nile").distance_km(31.2, 30.0) < 30


def test_region_target_uses_distance_only(world):
    sahara = areas(world, "region:Sahara")
    assert sahara[0].distance_km(5.0, 23.0) == 0.0
    # Lagos is a few hundred km south of the desert edge: close.
    nigeria = world.country_at(3.4, 6.5)
    assert nigeria.id == "country:Nigeria"
    assert world.is_close(sahara, 3.4, 6.5, nigeria)
    # Paris is ~1500 km north of it; Cape Town is much farther.
    assert not world.is_close(sahara, *PARIS, world.find("country:France"))
    assert not world.is_close(sahara, 18.4, -33.9, world.find("country:South Africa"))


def test_continent_and_ocean_targets_use_distance(world):
    africa = areas(world, "continent:Africa")
    assert world.is_close(africa, -3.7, 40.42)        # Madrid, ~500 km from Morocco
    assert not world.is_close(africa, 37.62, 55.75)   # Moscow
    atlantic = areas(world, "ocean:Atlantic Ocean")
    assert world.is_close(atlantic, *PARIS)
    assert not world.is_close(atlantic, 83.0, 55.0)   # Novosibirsk


# ---- several targets ------------------------------------------------------------------------
def test_close_to_any_of_several_targets(world):
    targets = areas(world, "country:Australia", "country:France", "country:Japan")
    assert world.is_close(targets, *ATLANTIC_NEAR_FRANCE)
    assert world.is_close(list(reversed(targets)), *ATLANTIC_NEAR_FRANCE)
    assert not world.is_close(targets, *ATLANTIC_FAR)


def test_neighbour_of_any_of_several_targets(world):
    targets = areas(world, "country:Australia", "country:Russia")
    china = world.find("country:China")
    assert world.is_close(targets, *CENTRAL_CHINA, china)
    assert not world.is_close(areas(world, "country:Australia"), *CENTRAL_CHINA, china)


def test_no_targets_is_never_close(world):
    assert not world.is_close([], *PARIS, world.find("country:France"))


# ---- antimeridian -----------------------------------------------------------------------------
def test_point_at_179_east_is_close_to_something_at_179_west(world):
    island = Area("country", "Dateline Island",
                  polys=[[[(-179.5, -1.0), (-178.5, -1.0), (-178.5, 1.0), (-179.5, 1.0)]]])
    # 1.5 degrees of longitude at the equator, not 358.5.
    assert island.distance_km(179.0, 0.0) == pytest.approx(167, abs=10)
    assert island.distance_km(179.0, 0.0, 1000) == pytest.approx(167, abs=10)
    assert world.is_close([island], 179.0, 0.0)


def test_antimeridian_the_other_way_round(world):
    island = Area("country", "West Dateline Island",
                  polys=[[[(178.5, -1.0), (179.5, -1.0), (179.5, 1.0), (178.5, 1.0)]]])
    assert island.distance_km(-179.0, 0.0) == pytest.approx(167, abs=10)
    assert world.is_close([island], -179.0, 0.0)
    assert not world.is_close([island], -160.0, 0.0)   # ~2200 km east


def test_antimeridian_line_target(world):
    cable = Area("river", "Dateline Creek", lines=[[(-179.0, -3.0), (-179.0, 3.0)]])
    assert cable.distance_km(179.0, 0.0) == pytest.approx(222, abs=10)
    assert world.is_close([cable], 179.0, 0.0)


def test_real_countries_across_the_date_line(world):
    # Samoa (172 W) seen from just west of the date line at the same latitude.
    samoa = world.find("country:Samoa")
    assert samoa.bbox[2] < -170
    d = samoa.distance_km(179.0, -13.8)
    assert d == pytest.approx(vertex_km(samoa, 179.0, -13.8), rel=0.05)
    assert 500 < d < 1000
    assert world.is_close([samoa], 179.0, -13.8)
    # Alaska's mainland from the Russian side of the Bering Strait.
    usa = world.find("country:United States of America")
    assert world.is_close([usa], -172.0, 64.5)


# ---- the far side of the globe is never close ---------------------------------------------------
def test_distance_to_a_country_on_the_far_side_of_the_globe_is_large(world):
    # North Pacific on France's latitude, 180 degrees of longitude away.
    france = world.find("country:France")
    assert vertex_km(france, 179.0, 47.0) > 8000
    assert france.distance_km(179.0, 47.0) > 3000


@pytest.mark.parametrize("ref", ["country:Russia", "continent:Asia"])
def test_gulf_of_alaska_is_not_close_to_russia_or_asia(world, ref):
    # Open Pacific south of Alaska: well over 2000 km from Russia, with
    # Alaska in between.
    target = world.find(ref)
    assert world.country_at(*GULF_OF_ALASKA) is None
    assert vertex_km(target, *GULF_OF_ALASKA) > 2000
    assert not world.is_close([target], *GULF_OF_ALASKA)


def test_round_click_in_the_gulf_of_alaska_is_wrong_for_russia(world, px):
    outcome = round_for(world, "country:Russia").click(*GULF_OF_ALASKA, px)
    assert outcome.kind == "wrong"


# ---- Outcome.kind through Round.click ---------------------------------------------------------------
@pytest.mark.parametrize("target, lon, lat, kind", [
    ("country:France", *PARIS, "correct"),
    ("country:France", *BERLIN, "close"),             # neighbour
    ("country:France", *MADRID, "close"),             # neighbour
    ("country:France", -8.6, 41.15, "close"),         # Porto: no border, ~600 km
    ("country:France", *ATLANTIC_NEAR_FRANCE, "close"),
    ("country:France", *ATLANTIC_FAR, "wrong"),
    ("country:France", *BRASILIA, "wrong"),
    ("country:France", 37.62, 55.75, "wrong"),        # Moscow
    ("country:France", 139.7, 35.7, "wrong"),         # Tokyo
    ("country:Russia", *CENTRAL_CHINA, "close"),      # neighbour, 2000 km from the border
    ("country:Russia", *SOUTH_KAZAKHSTAN, "close"),
    ("country:Russia", 78.0, 20.0, "wrong"),          # India
    ("country:Australia", 174.8, -41.3, "wrong"),     # Wellington, ~2200 km
    ("river:Nile", 27.0, 27.0, "close"),
    ("river:Nile", 20.0, 25.0, "wrong"),
    ("region:Sahara", 3.4, 6.5, "close"),             # Lagos
    ("region:Sahara", 18.4, -33.9, "wrong"),          # Cape Town
    ("continent:Africa", 37.62, 55.75, "wrong"),
    ("ocean:Atlantic Ocean", 83.0, 55.0, "wrong"),
])
def test_round_outcome_kind(world, px, target, lon, lat, kind):
    outcome = round_for(world, target).click(lon, lat, px)
    assert outcome.kind == kind


def test_round_outcome_reports_what_was_clicked(world, px):
    r = round_for(world, "country:France")
    assert r.click(*BERLIN, px).clicked is world.find("country:Germany")
    assert r.click(-35.0, 30.0, px).clicked is world.find("ocean:Atlantic Ocean")
    assert r.click(-75.0, 15.0, px).clicked is world.find("sea:Caribbean Sea")


def test_round_close_and_wrong_with_several_targets(world, px):
    r = round_for(world, "country:Australia", "country:France")
    assert r.click(*BERLIN, px).kind == "close"
    assert r.click(*BRASILIA, px).kind == "wrong"
    assert r.click(134.0, -25.0, px).kind == "correct"


@pytest.mark.parametrize("lon", [-170, -90, -30, 48.37, 120, 179])
def test_antarctic_coast_is_close_to_the_globe_circling_southern_ocean(world, lon):
    # The Southern Ocean ring runs all the way round the globe; a point just
    # inland on Antarctica must be near it at every longitude.
    ocean = world.find("ocean:Southern Ocean")
    assert ocean.distance_km(lon, -74.0) < 1000
    assert world.is_close([ocean], lon, -74.0)


def test_mid_pacific_is_close_to_the_pacific_but_not_to_the_southern_ocean(world):
    pacific = world.find("ocean:Pacific Ocean")
    southern = world.find("ocean:Southern Ocean")
    assert pacific.distance_km(-140, 0) == 0
    assert southern.distance_km(-140, 0) > 5000
