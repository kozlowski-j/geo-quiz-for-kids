"""The collection counters (what has been found so far) and the "look in here" box."""
import random

import pytest

from geoquiz import tasks as T

PX = 1920 / 360  # whole-world view on a full-HD screen
MID_PACIFIC = (-140.0, -30.0)


def make_task(world, task_id, task_type, *refs):
    return T.Task(task_id, task_type, "prompt", list(refs), 2, [world.find(r) for r in refs])


# ---- categories -------------------------------------------------------------------
@pytest.mark.parametrize("task_type, ref, category", [
    ("country", "country:France", "countries"),
    ("animal", "country:Kenya", "animals"),
    ("feature", "continent:Africa", "continents"),
    ("feature", "ocean:Pacific Ocean", "water"),
    ("feature", "sea:Caribbean Sea", "water"),
    ("feature", "river:Nile", "water"),
    ("feature", "lake:Lake Victoria", "water"),
    ("feature", "region:Himalayas", "mountains"),
    ("feature", "region:Sahara", "places"),
    ("feature", "region:Madagascar", "places"),
])
def test_task_category(world, task_type, ref, category):
    assert T.task_category(make_task(world, "t", task_type, ref)) == category


def test_every_real_task_has_a_category_and_every_category_has_tasks(world):
    tasks, _ = T.load_tasks(world)
    counts = {c: 0 for c in T.CATEGORIES}
    for task in tasks:
        counts[T.task_category(task)] += 1
    assert all(counts.values()), counts
    assert sum(counts.values()) == len(tasks)


# ---- what counts as found ----------------------------------------------------------
def test_collection_counts_found_tasks_per_category(world, tmp_path):
    tasks = [make_task(world, "fr", "country", "country:France"),
             make_task(world, "de", "country", "country:Germany"),
             make_task(world, "nile", "feature", "river:Nile")]
    progress = T.Progress(tmp_path / "p.json")
    assert T.collection(tasks, progress) == [("countries", 0, 2), ("water", 0, 1)]
    progress.record("fr", missed=False)
    progress.record("nile", missed=True, found=True)   # found on the second try, before the answer
    assert T.collection(tasks, progress) == [("countries", 1, 2), ("water", 1, 1)]
    progress.save()
    assert T.collection(tasks, T.Progress(tmp_path / "p.json")) == [("countries", 1, 2), ("water", 1, 1)]
    assert T.collection(tasks, None) == [("countries", 0, 2), ("water", 0, 1)]


def test_found_is_kept_even_if_he_misses_it_later(tmp_path):
    progress = T.Progress(tmp_path / "p.json")
    progress.record("a", missed=False)
    progress.record("a", missed=True, found=False)
    assert progress.found("a") and progress.missed_last_time("a")


def test_needing_the_answer_shown_does_not_count_as_found(tmp_path):
    progress = T.Progress(tmp_path / "p.json")
    progress.record("a", missed=True, found=False)
    assert not progress.found("a")
    assert not progress.found("never-seen")


def test_old_save_files_without_the_found_flag_are_understood(tmp_path):
    progress = T.Progress(tmp_path / "p.json")
    progress.tasks = {"clean": {"seen": 2, "missed": 1, "last_missed": True},
                      "always-wrong": {"seen": 2, "missed": 2, "last_missed": True}}
    assert progress.found("clean")            # one of the two rounds had no wrong click
    assert not progress.found("always-wrong")


def test_round_marks_a_task_found_only_without_the_shown_answer(world, tmp_path):
    progress = T.Progress(tmp_path / "p.json")
    tasks = [make_task(world, "fr", "country", "country:France"),
             make_task(world, "br", "country", "country:Brazil")]
    rnd = T.Round(world, tasks, progress)
    rnd.click(*MID_PACIFIC, PX)                       # one miss, then right: still found
    assert rnd.click(2.35, 48.86, PX).star
    rnd.advance()
    for _ in range(3):                                # three misses: the answer is shown
        rnd.click(*MID_PACIFIC, PX)
    assert rnd.click(-50.0, -10.0, PX).star is False
    assert progress.found("fr") and not progress.found("br")


# ---- the search box -----------------------------------------------------------------
@pytest.mark.parametrize("ref", ["country:France", "country:Russia", "country:Malta", "river:Nile",
                                 "continent:Asia", "ocean:Arctic Ocean", "region:Sahara"])
@pytest.mark.parametrize("seed", range(5))
def test_search_zone_contains_the_target_and_stays_on_the_map(world, ref, seed):
    area = world.find(ref)
    zone = T.search_zone([area], random.Random(seed))
    box = area.main_box
    assert zone[0] <= box[0] and zone[1] <= box[1]
    assert zone[2] >= min(box[2], T.WORLD_BOX[2]) and zone[3] >= min(box[3], T.WORLD_BOX[3])
    assert T.WORLD_BOX[0] <= zone[0] < zone[2] <= T.WORLD_BOX[2]
    assert T.WORLD_BOX[1] <= zone[1] < zone[3] <= T.WORLD_BOX[3]


def test_search_zone_is_bigger_than_a_small_target_and_not_centred_on_it(world):
    malta = world.find("country:Malta")
    cx = (malta.main_box[0] + malta.main_box[2]) / 2
    centres = set()
    for seed in range(8):
        zone = T.search_zone([malta], random.Random(seed))
        assert zone[2] - zone[0] >= 20 and zone[3] - zone[1] >= 16   # never a giveaway
        centres.add(round((zone[0] + zone[2]) / 2 - cx, 2))
    assert len(centres) > 4 and any(abs(c) > 1 for c in centres)


def test_search_zone_for_several_targets_surrounds_the_biggest(world):
    kenya, russia = world.find("country:Kenya"), world.find("country:Russia")
    zone = T.search_zone([kenya, russia], random.Random(1))
    assert zone[0] <= russia.main_box[0] and zone[3] >= min(russia.main_box[3], 84)


def test_round_shows_the_zone_after_two_misses_and_the_answer_after_three(world):
    rnd = T.Round(world, [make_task(world, "fr", "country", "country:France"),
                          make_task(world, "br", "country", "country:Brazil")], rng=random.Random(2))
    first = rnd.click(*MID_PACIFIC, PX)
    assert not first.zone_started and rnd.zone is None
    second = rnd.click(*MID_PACIFIC, PX)
    assert second.zone_started and not second.hint_started
    zone = rnd.zone
    assert zone is not None and zone[0] <= 2.35 <= zone[2] and zone[1] <= 48.86 <= zone[3]
    third = rnd.click(*MID_PACIFIC, PX)
    assert third.hint_started and not third.zone_started and rnd.zone == zone   # the box does not jump
    assert rnd.click(2.35, 48.86, PX).star is False
    rnd.advance()
    assert rnd.zone is None                                                     # fresh for the next task


def test_a_correct_second_click_never_shows_the_zone(world):
    rnd = T.Round(world, [make_task(world, "fr", "country", "country:France")])
    rnd.click(*MID_PACIFIC, PX)
    assert rnd.click(2.35, 48.86, PX).star and rnd.zone is None
