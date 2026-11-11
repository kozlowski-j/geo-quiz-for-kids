"""Hit detection on the real map: which country / sea is under a click."""
import pytest

from geoquiz import tasks as T
from geoquiz.mapdata import Area

PARIS = (2.35, 48.86)
GENEVA = (6.14, 46.2)
BAY_OF_BISCAY = (-4.0, 45.5)
BELGIUM = (4.5, 50.6)
LESOTHO = (28.2, -29.6)
JOHANNESBURG = (28.05, -26.2)
CAIRO = (31.2, 30.0)
MID_ATLANTIC = (-35.0, 30.0)
CARIBBEAN = (-75.0, 15.0)


def name_of(area):
    return area.id if area is not None else None


# ---- lookup -----------------------------------------------------------------
@pytest.mark.parametrize("ref", [
    "country:France", "continent:Africa", "ocean:Pacific Ocean", "sea:Mediterranean Sea",
    "region:Sahara", "river:Nile", "lake:Lake Victoria",
])
def test_every_kind_of_area_can_be_found(world, ref):
    area = world.find(ref)
    assert area is not None
    assert area.id == ref
    assert area.kind == ref.split(":")[0]


@pytest.mark.parametrize("ref", [
    "country:france", "COUNTRY:FRANCE", "Country:France", "  country:France  ",
])
def test_lookup_is_case_insensitive(world, ref):
    assert world.find(ref) is world.find("country:France")


def test_lookup_ignores_extra_spaces_inside_a_name(world):
    assert world.find("ocean:atlantic   ocean") is world.find("ocean:Atlantic Ocean")


@pytest.mark.parametrize("alias, name", [
    ("country:FRA", "France"), ("country:fra", "France"),
    ("country:DEU", "Germany"), ("country:USA", "United States of America"),
])
def test_three_letter_code_is_an_alias(world, alias, name):
    assert world.find(alias) is world.find(f"country:{name}")


@pytest.mark.parametrize("ref", [
    "country:Atlantis", "France", "river:France", "country:", "", "planet:Mars",
])
def test_unknown_ids(world, ref):
    assert world.find(ref) is None
    with pytest.raises(KeyError):
        world.resolve(ref)


def test_resolve_returns_the_same_area_as_find(world):
    assert world.resolve("river:nile") is world.find("river:Nile")


def test_all_ids_are_unique_sorted_and_resolvable(world):
    ids = world.all_ids()
    assert ids == sorted(set(ids))
    assert "country:France" in ids and "country:FRA" not in ids
    kinds = {i.split(":")[0] for i in ids}
    assert kinds == {"country", "continent", "ocean", "sea", "region", "river", "lake"}
    for i in ids:
        assert world.find(i).id == i


# ---- countries: real shapes, not bounding boxes -------------------------------
@pytest.mark.parametrize("lon, lat, country", [
    (*PARIS, "France"),
    (*GENEVA, "Switzerland"),
    (*BELGIUM, "Belgium"),
    (13.4, 52.52, "Germany"),          # Berlin
    (-3.7, 40.42, "Spain"),            # Madrid
    (-0.1, 51.5, "United Kingdom"),    # London
    (37.62, 55.75, "Russia"),          # Moscow
    (83.0, 55.0, "Russia"),            # Novosibirsk
    (139.7, 35.7, "Japan"),            # Tokyo
    (*CAIRO, "Egypt"),
    (*JOHANNESBURG, "South Africa"),
    (*LESOTHO, "Lesotho"),
    (-47.9, -15.8, "Brazil"),          # Brasilia
    (-100.0, 40.0, "United States of America"),
    (-150.0, 64.0, "United States of America"),   # Alaska
    (-155.5, 19.6, "United States of America"),   # Hawaii (Big Island)
    (-110.0, 60.0, "Canada"),
    (134.0, -25.0, "Australia"),
    (146.5, -42.0, "Australia"),       # Tasmania
    (-53.0, 4.0, "France"),            # French Guiana
    (9.1, 42.1, "France"),             # Corsica
    (14.0, 37.5, "Italy"),             # Sicily
    (-18.0, 65.0, "Iceland"),
    (47.0, -19.0, "Madagascar"),
    (80.7, 7.5, "Sri Lanka"),
    (-42.0, 72.0, "Greenland"),
])
def test_country_at(world, lon, lat, country):
    assert name_of(world.country_at(lon, lat)) == f"country:{country}"
    assert world.find(f"country:{country}").contains(lon, lat)


def test_paris_is_in_france_only(world):
    france = world.find("country:France")
    assert france.contains(*PARIS)
    for other in ("Germany", "Belgium", "Spain", "Switzerland", "United Kingdom"):
        assert not world.find(f"country:{other}").contains(*PARIS)


@pytest.mark.parametrize("lon, lat, what", [
    (*GENEVA, "Geneva (Switzerland)"),
    (*BAY_OF_BISCAY, "Bay of Biscay"),
    (*BELGIUM, "central Belgium"),
    (7.5, 44.6, "Piedmont (Italy)"),
    (5.0, 43.0, "Mediterranean off Marseille"),
    (-30.0, 20.0, "mid Atlantic, inside France's world-wide bounding box"),
    (-47.9, -15.8, "Brasilia, inside France's world-wide bounding box"),
])
def test_point_in_frances_bounding_box_but_not_in_france(world, lon, lat, what):
    france = world.find("country:France")
    b = france.bbox
    assert b[0] <= lon <= b[2] and b[1] <= lat <= b[3], "test point must be in the bbox"
    assert not france.contains(lon, lat), what
    assert not france.hit(lon, lat), what
    assert world.country_at(lon, lat) is not france


def test_sea_points_are_no_country(world):
    for point in (BAY_OF_BISCAY, MID_ATLANTIC, CARIBBEAN, (80.0, -30.0), (-140.0, 0.0)):
        assert world.country_at(*point) is None


# ---- enclaves (holes) -----------------------------------------------------------
def test_lesotho_is_a_hole_in_south_africa(world):
    south_africa = world.find("country:South Africa")
    lesotho = world.find("country:Lesotho")
    assert lesotho.contains(*LESOTHO)
    assert not south_africa.contains(*LESOTHO)
    assert world.country_at(*LESOTHO) is lesotho
    # ...although the point is well inside South Africa's bounding box.
    b = south_africa.bbox
    assert b[0] < LESOTHO[0] < b[2] and b[1] < LESOTHO[1] < b[3]


def test_johannesburg_is_south_africa_not_lesotho(world):
    assert world.find("country:South Africa").contains(*JOHANNESBURG)
    assert not world.find("country:Lesotho").contains(*JOHANNESBURG)
    assert name_of(world.country_at(*JOHANNESBURG)) == "country:South Africa"


def test_distance_from_inside_a_hole_is_to_the_edge_of_the_hole(world):
    """From the middle of Lesotho, South Africa is about 60 km away in every
    direction, not the 250 km to its outer border."""
    south_africa = world.find("country:South Africa")
    assert not south_africa.contains(*LESOTHO)
    assert 20 < south_africa.distance_km(*LESOTHO) < 120
    assert south_africa.distance_km(*LESOTHO, 1000) == pytest.approx(south_africa.distance_km(*LESOTHO))
    # In step with the distance in degrees, which always looked at the hole.
    assert south_africa.distance_km(*LESOTHO) == pytest.approx(
        south_africa.distance_deg(*LESOTHO) * 111.2, rel=0.2)


def test_all_around_lesotho_is_south_africa(world):
    south_africa = world.find("country:South Africa")
    for lon, lat in [(28.2, -28.2), (28.2, -31.0), (26.5, -29.6), (29.8, -29.6)]:
        assert world.country_at(lon, lat) is south_africa


@pytest.mark.parametrize("lon, lat, enclave, around", [
    (12.46, 43.94, "San Marino", "Italy"),
    (31.5, -26.5, "eSwatini", None),   # Swaziland, between South Africa and Mozambique
])
def test_other_small_enclosed_countries(world, lon, lat, enclave, around):
    found = world.country_at(lon, lat)
    if world.find(f"country:{enclave}") is None:
        pytest.skip(f"{enclave} has another name in this data set")
    assert name_of(found).lower() == f"country:{enclave}".lower()
    if around:
        assert not world.find(f"country:{around}").contains(lon, lat)


# ---- multi-part countries ---------------------------------------------------------
def test_multi_part_countries_have_several_polygons(world):
    for name in ("United States of America", "France", "Australia", "Indonesia", "Japan"):
        assert len(world.find(f"country:{name}").polys) > 1, name


@pytest.mark.parametrize("lon, lat, part", [
    (-150.0, 64.0, "Alaska"), (-155.5, 19.6, "Hawaii"), (-98.0, 39.0, "Kansas"),
])
def test_parts_of_the_united_states(world, lon, lat, part):
    usa = world.find("country:United States of America")
    assert usa.contains(lon, lat), part
    assert world.country_at(lon, lat) is usa, part


def test_gap_between_alaska_and_the_lower_states_is_canada(world):
    # Inside the bounding box of the United States but not in any of its parts.
    usa = world.find("country:United States of America")
    assert not usa.contains(-125.0, 57.0)
    assert name_of(world.country_at(-125.0, 57.0)) == "country:Canada"


def test_tasmania_and_bass_strait(world):
    australia = world.find("country:Australia")
    assert australia.contains(146.5, -42.0)
    # The strait between Tasmania and the mainland is water.
    assert not australia.contains(146.0, -39.8)
    assert world.country_at(146.0, -39.8) is None


def test_french_guiana_is_france_but_its_neighbours_are_not(world):
    france = world.find("country:France")
    assert world.country_at(-53.0, 4.0) is france
    assert name_of(world.country_at(-56.0, 4.0)) == "country:Suriname"
    assert name_of(world.country_at(-52.0, 0.0)) == "country:Brazil"


# ---- tolerance --------------------------------------------------------------------
def _east_of(area, degrees):
    """A point `degrees` east of the area's bounding box, at mid height."""
    b = area.bbox
    return (b[2] + degrees, (b[1] + b[3]) / 2)


@pytest.mark.parametrize("island", ["Mauritius", "Malta", "Barbados"])
def test_point_just_offshore_of_a_small_island_country(world, island):
    area = world.find(f"country:{island}")
    lon, lat = _east_of(area, 0.5)
    assert world.country_at(lon, lat) is None
    assert not area.contains(lon, lat)
    assert not area.hit(lon, lat)                 # no tolerance: must be inside
    assert not area.hit(lon, lat, 0.0)
    assert not area.hit(lon, lat, 0.05)           # tiny tolerance
    assert not area.hit(lon, lat, 0.45)
    assert area.hit(lon, lat, 0.6)
    assert area.hit(lon, lat, 2.8)                # 15 px on the whole-world view


def test_hit_tolerance_is_a_distance_not_a_bounding_box_margin(world):
    # Diagonally off the corner of Mauritius' box the distance is > 1 degree
    # even though both coordinates are within 1 degree of the box.
    area = world.find("country:Mauritius")
    b = area.bbox
    lon, lat = b[2] + 0.9, b[3] + 0.9
    assert area.distance_deg(lon, lat) > 1.0
    assert not area.hit(lon, lat, 1.0)
    assert area.hit(lon, lat, 1.6)


def test_distance_deg_is_zero_inside_and_grows_outside(world):
    france = world.find("country:France")
    assert france.distance_deg(*PARIS) == 0.0
    mauritius = world.find("country:Mauritius")
    near = mauritius.distance_deg(*_east_of(mauritius, 0.5))
    far = mauritius.distance_deg(*_east_of(mauritius, 2.0))
    assert near == pytest.approx(0.5, abs=0.02)
    assert far == pytest.approx(2.0, abs=0.02)


def test_distance_deg_measures_to_the_real_border(world):
    france = world.find("country:France")
    # Geneva sits in a pocket of Switzerland a few km from the French border.
    assert 0 < france.distance_deg(*GENEVA) < 0.2
    # Central Belgium is roughly half a degree from France.
    assert 0.2 < france.distance_deg(*BELGIUM) < 1.2


def test_distance_deg_limit_skips_far_pieces(world):
    mauritius = world.find("country:Mauritius")
    lon, lat = _east_of(mauritius, 5.0)
    assert mauritius.distance_deg(lon, lat) == pytest.approx(5.0, abs=0.05)
    assert mauritius.distance_deg(lon, lat, limit=1.0) > 1.0


def test_hit_inside_needs_no_tolerance(world):
    france = world.find("country:France")
    assert france.hit(*PARIS)
    assert france.hit(*PARIS, 0.0)
    assert france.hit(*PARIS, 3.0)


def test_area_without_any_shape_is_never_hit():
    empty = Area("region", "Nowhere")
    assert not empty.contains(0, 0)
    assert not empty.hit(0, 0, 5.0)
    assert empty.size_deg == 0.0


def test_synthetic_area_with_hole():
    outline = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6)]
    area = Area("region", "Donut", polys=[[outline, hole]])
    assert area.id == "region:Donut"
    assert area.contains(1, 1)
    assert not area.contains(5, 5)
    assert area.size_deg == pytest.approx(10)
    # From the middle of the hole the nearest edge is the hole's, 1 degree away.
    assert area.distance_deg(5, 5) == pytest.approx(1)
    assert area.hit(5, 5, 1.01)
    assert not area.hit(5, 5, 0.9)
    assert area.distance_deg(12, 5) == pytest.approx(2)


# ---- rivers are lines ----------------------------------------------------------------
def test_nile_is_made_of_lines_only(world):
    nile = world.find("river:Nile")
    assert nile.polys == []
    assert len(nile.lines) >= 1
    assert nile.size_deg > 5


@pytest.mark.parametrize("lon, lat", [CAIRO, (32.5, 15.6), (31.0, 25.0), (33.0, 0.5), (0.0, 0.0)])
def test_river_never_contains_a_point(world, lon, lat):
    nile = world.find("river:Nile")
    assert not nile.contains(lon, lat)
    assert not nile.hit(lon, lat)  # zero tolerance can never hit a line


def test_nile_is_hit_near_cairo_with_tolerance(world):
    nile = world.find("river:Nile")
    assert nile.distance_deg(*CAIRO) < 0.3
    assert nile.hit(*CAIRO, 0.5)
    assert nile.hit(*CAIRO, 2.8)
    assert not nile.hit(*CAIRO, 0.001)


@pytest.mark.parametrize("lon, lat", [
    (20.0, 25.0),     # Libyan desert, 1000 km west
    (45.0, 25.0),     # Saudi Arabia
    (31.2, 40.0),     # Turkey, north of the delta
    (-60.0, -3.0),    # the Amazon instead
])
def test_nile_is_not_hit_far_away(world, lon, lat):
    nile = world.find("river:Nile")
    assert not nile.hit(lon, lat, 2.8)


def test_other_rivers_work_the_same_way(world):
    amazon = world.find("river:Amazon")
    assert amazon is not None and not amazon.polys
    assert amazon.hit(-60.0, -3.2, 1.0)        # near Manaus
    assert not amazon.hit(*CAIRO, 2.8)


# ---- continents ---------------------------------------------------------------------
@pytest.mark.parametrize("lon, lat, continent", [
    (37.62, 55.75, "Europe"),          # Moscow
    (83.0, 55.0, "Asia"),              # Novosibirsk
    (47.0, -19.0, "Africa"),           # Madagascar
    (139.7, 35.7, "Asia"),             # Tokyo
    (-0.1, 51.5, "Europe"),            # London
    (*PARIS, "Europe"),
    (*CAIRO, "Africa"),
    (*JOHANNESBURG, "Africa"),
    (*LESOTHO, "Africa"),
    (116.4, 39.9, "Asia"),             # Beijing
    (77.2, 28.6, "Asia"),              # Delhi
    (-100.0, 40.0, "North America"),
    (-150.0, 64.0, "North America"),   # Alaska
    (-47.9, -15.8, "South America"),
    (-53.0, 4.0, "South America"),     # French Guiana: France, but not Europe
    (134.0, -25.0, "Australia"),
    (146.5, -42.0, "Australia"),       # Tasmania
    (0.0, -80.0, "Antarctica"),
])
def test_point_is_in_exactly_one_continent(world, lon, lat, continent):
    names = ("Africa", "Antarctica", "Asia", "Australia", "Europe", "North America",
             "South America")
    inside = [n for n in names if world.find(f"continent:{n}").contains(lon, lat)]
    assert inside == [continent]


def test_russia_is_split_between_europe_and_asia(world):
    europe = world.find("continent:Europe")
    asia = world.find("continent:Asia")
    russia = world.find("country:Russia")
    assert russia.contains(37.62, 55.75) and russia.contains(83.0, 55.0)
    assert europe.contains(37.62, 55.75) and not asia.contains(37.62, 55.75)
    assert asia.contains(83.0, 55.0) and not europe.contains(83.0, 55.0)


def test_sea_points_are_in_no_continent(world):
    for name in ("Africa", "Asia", "Europe", "North America", "South America", "Australia"):
        continent = world.find(f"continent:{name}")
        assert not continent.contains(*MID_ATLANTIC)
        assert not continent.contains(*BAY_OF_BISCAY)


# ---- oceans and seas ------------------------------------------------------------------
def test_atlantic_is_a_composite_that_includes_its_seas(world):
    atlantic = world.find("ocean:Atlantic Ocean")
    assert atlantic.contains(*MID_ATLANTIC)
    assert atlantic.contains(*CARIBBEAN)
    assert world.find("sea:Caribbean Sea").contains(*CARIBBEAN)
    assert not world.find("sea:Caribbean Sea").contains(*MID_ATLANTIC)


def test_water_at_prefers_the_sea_over_the_ocean(world):
    assert name_of(world.water_at(*CARIBBEAN)) == "sea:Caribbean Sea"
    assert name_of(world.water_at(*MID_ATLANTIC)) == "ocean:Atlantic Ocean"
    assert name_of(world.water_at(*BAY_OF_BISCAY)) == "sea:Bay of Biscay"


@pytest.mark.parametrize("lon, lat, ocean", [
    (-35.0, 30.0, "Atlantic Ocean"),
    (-20.0, -20.0, "Atlantic Ocean"),
    (-140.0, 0.0, "Pacific Ocean"),
    (170.0, 20.0, "Pacific Ocean"),
    (80.0, -30.0, "Indian Ocean"),
])
def test_open_ocean_points(world, lon, lat, ocean):
    assert name_of(world.water_at(lon, lat)) == f"ocean:{ocean}"
    for other in world.oceans:
        assert other.contains(lon, lat) == (other.name == ocean)


def test_oceans_do_not_contain_land(world):
    for ocean in world.oceans:
        assert not ocean.contains(*PARIS)
        assert not ocean.contains(83.0, 55.0)
        assert not ocean.contains(-47.9, -15.8)


def test_water_at_on_land_is_none(world):
    assert world.water_at(*PARIS) is None
    assert world.water_at(83.0, 55.0) is None


def test_mediterranean_is_a_sea(world):
    med = world.find("sea:Mediterranean Sea")
    assert med.contains(18.0, 35.0)       # between Sicily and Libya
    assert not med.contains(*PARIS)
    assert not med.contains(*MID_ATLANTIC)


def test_lake_victoria(world):
    lake = world.find("lake:Lake Victoria")
    assert lake.contains(33.0, -1.0)
    assert not lake.contains(36.8, -1.3)   # Nairobi


def test_sahara_region(world):
    sahara = world.find("region:Sahara")
    assert sahara.contains(5.0, 23.0)       # southern Algeria
    assert not sahara.contains(*PARIS)
    assert not sahara.contains(25.0, -5.0)  # Congo


# ---- Round.judge: the one place that decides what a click means ---------------------------
def test_judge_prefers_an_exact_hit_over_a_near_miss(world):
    france = world.find("country:France")
    luxembourg = world.find("country:Luxembourg")
    # Luxembourg is tiny, so at this zoom a click in it is within 15 px of France,
    # which is listed first. The country actually clicked must still win.
    refs = ["country:France", "country:Luxembourg"]
    rnd = T.Round(world, [T.Task("t", "country", "Find it.", refs, 2, [france, luxembourg])])
    lon, lat = 6.1, 49.75
    assert luxembourg.contains(lon, lat)
    assert france.hit(lon, lat, T.CLICK_TOLERANCE_PX / 5.0)
    kind, hit, clicked = rnd.judge(lon, lat, 5.0)
    assert (kind, hit, clicked) == ("correct", luxembourg, luxembourg)


def test_judge_changes_nothing_and_agrees_with_click(world, px):
    france = world.find("country:France")
    rnd = T.Round(world, [T.Task("t", "country", "Find France.", ["country:France"], 1, [france])])
    for point, expected in ((BELGIUM, "close"), (MID_ATLANTIC, "wrong"), (PARIS, "correct")):
        kind, hit, clicked = rnd.judge(*point, px)
        assert kind == expected
        assert (hit is france) == (expected == "correct")
        assert (rnd.wrong_attempts, rnd.solved, rnd.zone) == (0, False, None)  # judging is free
    assert rnd.judge(*BELGIUM, px)[2] is world.find("country:Belgium")
    assert rnd.judge(*MID_ATLANTIC, px)[2] is None  # only countries; the sea is named by click()
    for point in (BELGIUM, MID_ATLANTIC, PARIS):
        assert rnd.click(*point, px).kind == rnd_kind(world, france, point, px)


def rnd_kind(world, target, point, px):
    fresh = T.Round(world, [T.Task("t", "country", "Find it.", [target.id], 1, [target])])
    return fresh.judge(*point, px)[0]


# ---- click tolerance rules ----------------------------------------------------------------
def test_tolerance_is_15_px_normally(world, px):
    france = world.find("country:France")
    assert T.CLICK_TOLERANCE_PX == 15 and T.BORDER_SLOP_PX == 1 and T.SMALL_TARGET_PX == 30
    assert T.click_tolerance_deg(france, px, None) == pytest.approx(15 / px)
    assert T.click_tolerance_deg(france, px, france) == pytest.approx(15 / px)


def test_tolerance_is_border_slop_when_the_click_is_in_another_country(world, px):
    france = world.find("country:France")
    belgium = world.find("country:Belgium")
    assert france.size_deg * px >= 30
    assert T.click_tolerance_deg(france, px, belgium) == pytest.approx(T.BORDER_SLOP_PX / px)
    assert T.click_tolerance_deg(france, 16 * px, belgium) == pytest.approx(T.BORDER_SLOP_PX / (16 * px))


@pytest.mark.parametrize("small", ["Luxembourg", "Malta", "Belgium"])
def test_small_targets_keep_the_full_tolerance(world, px, small):
    target = world.find(f"country:{small}")
    germany = world.find("country:Germany")
    assert target.size_deg * px < 30
    assert T.click_tolerance_deg(target, px, germany) == pytest.approx(15 / px)


def test_small_target_gets_the_narrow_tolerance_once_zoomed_in(world, px):
    luxembourg = world.find("country:Luxembourg")
    germany = world.find("country:Germany")
    zoomed = 16 * px
    assert luxembourg.size_deg * zoomed >= 30
    assert T.click_tolerance_deg(luxembourg, zoomed, germany) == pytest.approx(T.BORDER_SLOP_PX / zoomed)


def test_big_target_counts_as_small_when_zoomed_far_out(world):
    france = world.find("country:France")
    belgium = world.find("country:Belgium")
    assert france.size_deg * 2.0 < 30
    assert T.click_tolerance_deg(france, 2.0, belgium) == pytest.approx(15 / 2.0)


def test_size_threshold_is_30_px_inclusive():
    target = Area("country", "Squareland", polys=[[[(0, 0), (6, 0), (6, 6), (0, 6)]]])
    other = Area("country", "Elsewhere", polys=[[[(10, 0), (11, 0), (11, 1), (10, 1)]]])
    assert target.size_deg == pytest.approx(6)
    assert T.click_tolerance_deg(target, 5.0, other) == pytest.approx(T.BORDER_SLOP_PX / 5.0)    # exactly 30 px
    assert T.click_tolerance_deg(target, 4.9, other) == pytest.approx(15 / 4.9)   # 29.4 px


def test_clicks_on_water_keep_the_full_tolerance(world, px):
    france = world.find("country:France")
    sea = world.find("sea:Bay of Biscay")
    assert T.click_tolerance_deg(france, px, None) == pytest.approx(15 / px)
    # A sea passed as "clicked" is not a different country either.
    assert T.click_tolerance_deg(france, px, sea) == pytest.approx(15 / px)


@pytest.mark.parametrize("ref", [
    "river:Nile", "region:Sahara", "continent:Europe", "ocean:Atlantic Ocean",
    "sea:Mediterranean Sea", "lake:Lake Victoria",
])
def test_non_country_targets_keep_the_full_tolerance(world, px, ref):
    egypt = world.find("country:Egypt")
    assert T.click_tolerance_deg(world.find(ref), px, egypt) == pytest.approx(15 / px)


def test_tolerance_in_degrees_shrinks_when_zooming_in(world, px):
    france = world.find("country:France")
    assert T.click_tolerance_deg(france, px, None) == pytest.approx(2.8125)
    assert T.click_tolerance_deg(france, 4 * px, None) == pytest.approx(2.8125 / 4)


# ---- the same rules through Round.click ------------------------------------------------------
def _round_for(world, *refs):
    task = T.Task("t", "country", "Find it.", list(refs), 2, [world.resolve(r) for r in refs])
    return T.Round(world, [task])


def test_round_clicking_paris_for_france_is_correct(world, px):
    outcome = _round_for(world, "country:France").click(*PARIS, px)
    assert outcome.kind == "correct"
    assert outcome.hit is world.find("country:France")
    assert outcome.clicked is world.find("country:France")


def test_round_clicking_central_belgium_for_france_is_not_correct(world, px):
    # Within 15 px of France on the whole-world view, but it is Belgium.
    france = world.find("country:France")
    assert france.hit(*BELGIUM, 15 / px)
    outcome = _round_for(world, "country:France").click(*BELGIUM, px)
    assert outcome.kind != "correct"
    assert outcome.hit is None
    assert outcome.clicked is world.find("country:Belgium")


@pytest.mark.parametrize("lon, lat", [
    (13.4, 52.52),   # Berlin
    (-3.7, 40.42),   # Madrid
    (12.5, 41.9),    # Rome
    (8.55, 47.37),   # Zurich
    (-0.1, 51.5),    # London
])
def test_round_clicking_a_neighbour_of_france_is_not_correct(world, px, lon, lat):
    assert _round_for(world, "country:France").click(lon, lat, px).kind != "correct"


def test_round_click_a_hair_across_the_border_still_counts(world, px):
    # Within the border slop of the French border, inside Belgium, from the French border near Lille.
    france = world.find("country:France")
    lon, lat = 3.2, 50.75
    assert world.country_at(lon, lat) is world.find("country:Belgium")
    assert france.distance_deg(lon, lat) < T.BORDER_SLOP_PX / px
    assert _round_for(world, "country:France").click(lon, lat, px).kind == "correct"


def test_round_click_in_the_sea_just_off_france_counts(world, px):
    # Bay of Biscay about 1 degree (5 px) off the coast: water, full tolerance.
    france = world.find("country:France")
    lon, lat = -2.6, 45.5
    assert world.country_at(lon, lat) is None
    assert 0.5 < france.distance_deg(lon, lat) < 15 / px
    assert _round_for(world, "country:France").click(lon, lat, px).kind == "correct"


@pytest.mark.parametrize("island", ["Mauritius", "Malta", "Barbados"])
def test_round_click_in_the_sea_a_few_pixels_off_a_small_island_counts(world, px, island):
    area = world.find(f"country:{island}")
    lon, lat = _east_of(area, 1.0)   # 1 degree is about 5 px
    assert world.country_at(lon, lat) is None
    outcome = _round_for(world, area.id).click(lon, lat, px)
    assert outcome.kind == "correct"
    assert outcome.hit is area
    assert outcome.clicked is None


def test_round_click_far_off_a_small_island_does_not_count(world, px):
    area = world.find("country:Mauritius")
    lon, lat = _east_of(area, 4.0)   # about 21 px
    assert _round_for(world, area.id).click(lon, lat, px).kind != "correct"


def test_round_same_offshore_click_misses_when_zoomed_in(world, px):
    # 1 degree off Mauritius is 5 px on the world view but 85 px at zoom 16.
    area = world.find("country:Mauritius")
    lon, lat = _east_of(area, 1.0)
    assert _round_for(world, area.id).click(lon, lat, 16 * px).kind != "correct"


def test_round_small_country_target_accepts_a_click_in_the_big_neighbour(world, px):
    # Luxembourg is a 3 px dot on the world view: a click 1 degree away in
    # Germany must still count, otherwise it is unhittable without zooming.
    luxembourg = world.find("country:Luxembourg")
    lon, lat = 7.2, 49.8
    assert world.country_at(lon, lat) is world.find("country:Germany")
    outcome = _round_for(world, "country:Luxembourg").click(lon, lat, px)
    assert outcome.kind == "correct" and outcome.hit is luxembourg


def test_round_lesotho_click_is_not_south_africa(world, px):
    assert _round_for(world, "country:Lesotho").click(*LESOTHO, px).kind == "correct"
    # Zoomed in a little, the middle of Lesotho is clearly not South Africa.
    assert _round_for(world, "country:South Africa").click(*LESOTHO, 4 * px).kind != "correct"
    assert _round_for(world, "country:South Africa").click(*JOHANNESBURG, px).kind == "correct"


def test_round_river_target_is_hit_near_its_line(world, px):
    assert _round_for(world, "river:Nile").click(*CAIRO, px).kind == "correct"
    assert _round_for(world, "river:Nile").click(20.0, 25.0, px).kind != "correct"


def test_round_any_part_of_a_multi_part_country_counts(world, px):
    for lon, lat in [(-150.0, 64.0), (-155.5, 19.6), (-98.0, 39.0)]:
        r = _round_for(world, "country:United States of America")
        assert r.click(lon, lat, px).kind == "correct"
    assert _round_for(world, "country:France").click(-53.0, 4.0, px).kind == "correct"
    assert _round_for(world, "country:Australia").click(146.5, -42.0, px).kind == "correct"


def test_round_continent_and_ocean_targets(world, px):
    assert _round_for(world, "continent:Europe").click(37.62, 55.75, px).kind == "correct"
    assert _round_for(world, "continent:Asia").click(83.0, 55.0, px).kind == "correct"
    assert _round_for(world, "continent:Asia").click(*PARIS, px).kind != "correct"
    assert _round_for(world, "ocean:Atlantic Ocean").click(*CARIBBEAN, px).kind == "correct"
    assert _round_for(world, "ocean:Atlantic Ocean").click(-140.0, 0.0, px).kind != "correct"
