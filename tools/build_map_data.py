"""Convert Natural Earth GeoJSON into the compact file the game bundles.

This is a one-off developer tool; the game itself never downloads anything.
The result (data/map/world.json.gz) is already committed, so you only need
this if you want to regenerate it.

Usage:
    python tools/build_map_data.py <folder with the GeoJSON files>

Required files (public domain, https://www.naturalearthdata.com/ - GeoJSON
copies at https://github.com/nvkelso/natural-earth-vector/tree/master/geojson):
    ne_50m_admin_0_countries.geojson
    ne_50m_geography_regions_polys.geojson
    ne_50m_geography_marine_polys.geojson
    ne_50m_rivers_lake_centerlines.geojson
    ne_50m_lakes.geojson
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from geoquiz.geometry import (  # noqa: E402
    point_in_polygon, ring_area, ring_centroid, simplify, simplify_ring,
)

OUT = ROOT / "data" / "map" / "world.json.gz"
PRECISION = 3            # decimals kept (about 100 m)
LOW_DETAIL_TOL = 0.04    # degrees; used for drawing when zoomed out
REGION_TOL = 0.02        # regions, seas and continents are fuzzy anyway

COUNTRY_NAMES = {  # Natural Earth NAME -> name used in the game
    "Dem. Rep. Congo": "Democratic Republic of the Congo",
    "Congo": "Republic of the Congo",
    "Central African Rep.": "Central African Republic",
    "Dominican Rep.": "Dominican Republic",
    "Eq. Guinea": "Equatorial Guinea",
    "Bosnia and Herz.": "Bosnia and Herzegovina",
    "S. Sudan": "South Sudan",
    "W. Sahara": "Western Sahara",
    "N. Cyprus": "Northern Cyprus",
    "eSwatini": "Eswatini",
    "Falkland Is.": "Falkland Islands",
    "Solomon Is.": "Solomon Islands",
    "Marshall Is.": "Marshall Islands",
    "Cook Is.": "Cook Islands",
    "Faeroe Is.": "Faroe Islands",
    "Cayman Is.": "Cayman Islands",
    "Antigua and Barb.": "Antigua and Barbuda",
    "St. Kitts and Nevis": "Saint Kitts and Nevis",
    "St. Vin. and Gren.": "Saint Vincent and the Grenadines",
    "Fr. Polynesia": "French Polynesia",
    "Fr. S. Antarctic Lands": "French Southern and Antarctic Lands",
    "S. Geo. and the Is.": "South Georgia",
    "Br. Indian Ocean Ter.": "British Indian Ocean Territory",
    "British Virgin Is.": "British Virgin Islands",
    "U.S. Virgin Is.": "United States Virgin Islands",
    "N. Mariana Is.": "Northern Mariana Islands",
    "Turks and Caicos Is.": "Turks and Caicos Islands",
    "Pitcairn Is.": "Pitcairn Islands",
    "Wallis and Futuna Is.": "Wallis and Futuna",
    "Heard I. and McDonald Is.": "Heard Island and McDonald Islands",
    "Ashmore and Cartier Is.": "Ashmore and Cartier Islands",
    "Indian Ocean Ter.": "Indian Ocean Territories",
    "St. Pierre and Miquelon": "Saint Pierre and Miquelon",
    "St-Martin": "Saint Martin",
    "St-Barthélemy": "Saint Barthelemy",
    "Åland": "Aland",
    "Côte d'Ivoire": "Ivory Coast",
    "São Tomé and Principe": "Sao Tome and Principe",
    "Curaçao": "Curacao",
}

# Seas that count as part of an ocean when the task is "find the ... Ocean".
OCEANS = {
    "Atlantic Ocean": [
        "North Atlantic Ocean", "South Atlantic Ocean", "Sargasso Sea", "Caribbean Sea",
        "Gulf of Mexico", "Labrador Sea", "Bay of Biscay", "North Sea", "Norwegian Sea",
        "Gulf of Guinea", "Gulf of Maine", "Gulf of Saint Lawrence", "Bay of Fundy",
        "Straits of Florida", "Gulf of Honduras", "Bahía de Campeche", "Irish Sea",
        "English Channel", "Bristol Channel", "Río de la Plata", "Golfo San Jorge",
        "Scotia Sea", "Chesapeake Bay", "Davis Strait",
    ],
    "Pacific Ocean": [
        "North Pacific Ocean", "South Pacific Ocean", "Philippine Sea", "Coral Sea",
        "Tasman Sea", "Bering Sea", "Gulf of Alaska", "Sea of Okhotsk", "Sea of Japan",
        "East China Sea", "South China Sea", "Yellow Sea", "Golfo de California",
        "Golfo de Panamá", "Solomon Sea", "Bismarck Sea", "Celebes Sea", "Sulu Sea",
        "Molucca Sea", "Bristol Bay", "Bay of Plenty", "Great Barrier Reef", "Luzon Strait",
    ],
    "Indian Ocean": [
        "INDIAN OCEAN", "Arabian Sea", "Bay of Bengal", "Andaman Sea", "Laccadive Sea",
        "Mozambique Channel", "Great Australian Bight", "Timor Sea", "Gulf of Aden",
        "Gulf of Oman", "Gulf of Mannar", "Gulf of Kutch",
    ],
    "Arctic Ocean": [
        "Arctic Ocean", "Barents Sea", "Kara Sea", "Laptev Sea", "Chukchi Sea",
        "Beaufort Sea", "Greenland Sea", "White Sea", "Baffin Bay", "Amundsen Gulf",
        "The North Western Passages", "Viscount Melville Sound", "Melville Bay",
    ],
    "Southern Ocean": [
        "SOUTHERN OCEAN", "Weddell Sea", "Ross Sea", "Amundsen Sea", "Bellingshausen Sea",
    ],
}

# Famous rivers assembled from the differently-named stretches in the data.
RIVERS = {
    "Nile": ["Nile", "El Bahr el Abyad", "Bahr el Jebel", "Albert Nile", "Victoria Nile",
             "Rosetta Branch", "Damietta Branch"],
    "Amazon": ["Amazonas"],
    "Mississippi": ["Mississippi"],
    "Missouri": ["Missouri"],
    "Yangtze": ["Yangtze", "Chang Jiang", "Jinsha", "Tongtian", "Tuotuo"],
    "Yellow River": ["Huang"],
    "Congo": ["Congo", "Lualaba"],
    "Niger": ["Niger"],
    "Zambezi": ["Zambezi"],
    "Danube": ["Danube", "Donau"],
    "Rhine": ["Rhine", "Rhein", "Rhin", "Nederrijn", "Lek", "Waal"],
    "Volga": ["Volga"],
    "Vistula": ["Vistula"],
    "Oder": ["Oder"],
    "Thames": ["Thames"],
    "Seine": ["Seine"],
    "Loire": ["Loire"],
    "Dnieper": ["Dnipro", "Dnepre"],
    "Ganges": ["Ganges"],
    "Indus": ["Indus"],
    "Mekong": ["Mekong", "Lancang"],
    "Euphrates": ["Euphrates", "Al Furat", "Firat"],
    "Tigris": ["Tigris", "Dicle"],
    "Ob": ["Ob"],
    "Yenisey": ["Yenisey"],
    "Lena": ["Lena"],
    "Amur": ["Amur", "Heilong Jiang"],
    "Murray": ["Murray"],
    "Yukon": ["Yukon"],
    "Mackenzie": ["Mackenzie"],
    "St. Lawrence": ["St. Lawrence"],
    "Colorado": ["Colorado"],
    "Rio Grande": ["Rio Grande"],
    "Orinoco": ["Orinoco"],
    "Paraná": ["Paraná"],
}

SMALL_WORDS = {"of", "and", "the", "de", "du", "des", "del", "la", "el", "al", "da", "do"}


def title_case(name):
    """NE writes important features in capitals: 'ROCKY MOUNTAINS' -> 'Rocky Mountains'."""
    if name != name.upper():
        return " ".join(name.split())
    words = []
    for i, word in enumerate(name.lower().split()):
        if i and word in SMALL_WORDS:
            words.append(word)
        else:
            words.append("-".join(part[:1].upper() + part[1:] for part in word.split("-")))
    return " ".join(words)


def load(folder, name):
    with open(Path(folder) / f"{name}.geojson", encoding="utf-8") as fh:
        return json.load(fh)["features"]


def rnd(ring):
    """Round and drop consecutive duplicates plus the closing point."""
    out = []
    for p in ring:
        q = (round(p[0], PRECISION), round(p[1], PRECISION))
        if not out or out[-1] != q:
            out.append(q)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def polygons_of(geometry, tolerance=0.0):
    coords = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        coords = [coords]
    polys = []
    for poly in coords:
        rings = []
        for i, ring in enumerate(poly):
            r = rnd(ring)
            if tolerance and r:
                r = simplify_ring(r, tolerance)
            if r and len(r) >= 3:
                rings.append(r)
            elif i == 0:
                break  # outline vanished, drop the polygon and its holes
        if rings:
            polys.append(rings)
    return polys


def lines_of(geometry, tolerance=0.0):
    coords = geometry["coordinates"]
    if geometry["type"] == "LineString":
        coords = [coords]
    out = []
    for line in coords:
        pts = []
        for p in line:
            q = (round(p[0], PRECISION), round(p[1], PRECISION))
            if not pts or pts[-1] != q:
                pts.append(q)
        if tolerance:
            pts = simplify(pts, tolerance)
        if len(pts) >= 2:
            out.append(pts)
    return out


def flat(ring):
    out = []
    for x, y in ring:
        out.append(x)
        out.append(y)
    return out


def flat_polys(polys):
    return [[flat(r) for r in poly] for poly in polys]


def simplified(polys, tolerance):
    """Low-detail copy for drawing: outlines only, tiny specks kept as-is."""
    out = []
    for poly in polys:
        ring = simplify_ring(poly[0], tolerance)
        out.append([ring if ring else poly[0]])
    return out


def build(folder):
    # ---- countries -------------------------------------------------------
    countries = []
    for f in load(folder, "ne_50m_admin_0_countries"):
        p = f["properties"]
        polys = polygons_of(f["geometry"])
        polys.sort(key=lambda poly: -ring_area(poly[0]))
        countries.append({
            "name": COUNTRY_NAMES.get(p["NAME"], p["NAME"]),
            "a3": p["ADM0_A3"],
            "continent": p["CONTINENT"],
            "color": int(p["MAPCOLOR9"]),
            "polys": polys,
        })
    names = [c["name"] for c in countries]
    assert len(set(names)) == len(names), "duplicate country names"

    # Neighbours: Natural Earth borders share their vertices exactly.
    owners = defaultdict(set)
    for i, c in enumerate(countries):
        home = c["polys"][0][0][0]
        for poly in c["polys"]:
            cx, cy = ring_centroid(poly[0])
            if abs(cx - home[0]) > 60 or abs(cy - home[1]) > 40:
                continue  # overseas territory (French Guiana does not make Brazil border France)
            for ring in poly:
                for pt in ring:
                    owners[pt].add(i)
    neighbours = defaultdict(set)
    for group in owners.values():
        if len(group) > 1:
            for a in group:
                neighbours[a].update(group - {a})

    # ---- regions and continents -----------------------------------------
    region_map = {}
    continents = {}
    for f in load(folder, "ne_50m_geography_regions_polys"):
        p = f["properties"]
        polys = polygons_of(f["geometry"], REGION_TOL)
        if not polys:
            continue
        name = title_case(p["NAME"])
        if p["FEATURECLA"] == "Continent":
            continents[name] = polys
            continue
        if p["FEATURECLA"] == "Lake":
            continue
        entry = region_map.setdefault(name, {"name": name, "class": p["FEATURECLA"], "polys": []})
        entry["polys"].extend(polys)

    # The continent shapes are mainland only. Add every island piece of every
    # country to the continent its country belongs to.
    continent_of = {"Oceania": "Australia"}

    def in_any_continent(x, y):
        return any(point_in_polygon(poly, x, y) for polys in continents.values() for poly in polys)

    for c in countries:
        target = continent_of.get(c["continent"], c["continent"])
        if target not in continents:
            continue  # "Seven seas (open ocean)"
        home = c["polys"][0][0][0]  # a point of the largest piece
        for poly in c["polys"]:
            cx, cy = ring_centroid(poly[0])
            if in_any_continent(cx, cy) or in_any_continent(*poly[0][0]):
                continue
            dest = target
            if c["a3"] == "RUS" and (cx > 60 or cx < -160):
                dest = "Asia"
            elif abs(cx - home[0]) > 60 or abs(cy - home[1]) > 40:
                continue  # far-flung overseas territory: leave it out
            ring = simplify_ring(poly[0], REGION_TOL) or poly[0]
            continents[dest].append([ring])

    # ---- seas and oceans --------------------------------------------------
    sea_map = {}
    for f in load(folder, "ne_50m_geography_marine_polys"):
        p = f["properties"]
        if p["featurecla"] == "river":
            continue
        polys = polygons_of(f["geometry"], REGION_TOL)
        if not polys:
            continue
        entry = sea_map.setdefault(p["name"], {"name": p["name"], "class": p["featurecla"], "polys": []})
        entry["polys"].extend(polys)
    oceans = []
    member_of = {}
    for ocean, members in OCEANS.items():
        present = []
        for m in members:
            if m not in sea_map:
                print(f"  note: sea {m!r} not in the data, skipped")
                continue
            member_of[m] = ocean
            present.append(m)
        oceans.append({"name": ocean, "members": present})
    seas = []
    for s in sea_map.values():
        if s["class"] == "ocean":
            continue  # only reachable through the combined ocean
        seas.append({"name": s["name"], "class": s["class"], "polys": flat_polys(s["polys"]),
                     "ocean": member_of.get(s["name"], "")})
    ocean_parts = [{"name": s["name"], "polys": flat_polys(s["polys"]), "ocean": member_of[s["name"]]}
                   for s in sea_map.values() if s["class"] == "ocean"]

    # ---- rivers and lakes -------------------------------------------------
    by_name = defaultdict(list)
    drawn_rivers = []
    for f in load(folder, "ne_50m_rivers_lake_centerlines"):
        p = f["properties"]
        lines = lines_of(f["geometry"], 0.01)
        if not lines:
            continue
        if p.get("name"):
            by_name[p["name"]].extend(lines)
        if (p.get("scalerank") or 9) <= 4:
            drawn_rivers.append({"rank": p["scalerank"], "lines": [flat(l) for l in lines]})
    rivers = []
    for name, parts in RIVERS.items():
        lines = [l for part in parts for l in by_name.get(part, [])]
        assert lines, f"river {name} has no geometry"
        rivers.append({"name": name, "lines": [flat(l) for l in lines]})

    lakes = []
    for f in load(folder, "ne_50m_lakes"):
        p = f["properties"]
        polys = polygons_of(f["geometry"], 0.01)
        if polys and p.get("name"):
            area = sum(ring_area(poly[0]) for poly in polys)
            lakes.append((area, {"name": p["name"], "polys": flat_polys([[poly[0]] for poly in polys])}))
    lakes.sort(key=lambda item: -item[0])
    lakes = [lake for _, lake in lakes[:30]]

    world = {
        "source": "Natural Earth 1:50m (public domain) - naturalearthdata.com",
        "countries": [{
            "name": c["name"], "a3": c["a3"], "continent": c["continent"], "color": c["color"],
            "neighbors": sorted(countries[j]["name"] for j in neighbours[i]),
            "polys": flat_polys(c["polys"]),
            "lo": flat_polys(simplified(c["polys"], LOW_DETAIL_TOL)),
        } for i, c in enumerate(countries)],
        "continents": [{"name": n, "polys": flat_polys(p)} for n, p in sorted(continents.items())],
        "regions": [{"name": r["name"], "class": r["class"], "polys": flat_polys(r["polys"])}
                    for r in sorted(region_map.values(), key=lambda r: r["name"])],
        "oceans": oceans,
        "ocean_parts": ocean_parts,
        "seas": sorted(seas, key=lambda s: s["name"]),
        "rivers": rivers,
        "drawn_rivers": drawn_rivers,
        "lakes": lakes,
    }
    return world


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    world = build(sys.argv[1])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(world, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with gzip.GzipFile(OUT, "wb", mtime=0) as fh:
        fh.write(raw)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB, {len(raw) / 1e6:.2f} MB unpacked)")
    for key in ("countries", "continents", "regions", "oceans", "seas", "rivers", "lakes"):
        print(f"  {key}: {len(world[key])}")


if __name__ == "__main__":
    main()
