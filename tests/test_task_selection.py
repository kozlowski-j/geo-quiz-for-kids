"""Task loading, saved progress, round selection and the Round engine."""
import json
import random
from collections import Counter

import pytest

from geoquiz import tasks as T

PARIS = (2.35, 48.86)
BRASILIA = (-47.9, -15.8)
TOKYO = (139.7, 35.7)


# ---- helpers ------------------------------------------------------------------
def make_tasks(level_counts):
    """Plain Task objects without map areas, e.g. {1: 20, 2: 5}."""
    out = []
    for level, count in level_counts.items():
        for i in range(count):
            out.append(T.Task(f"L{level}-{i:02d}", "country", f"Task {i}", [], level))
    return out


def ids(tasks):
    return [t.id for t in tasks]


def write_files(tmp_path, tasks, animals=None):
    tasks_path = tmp_path / "tasks.json"
    animals_path = tmp_path / "animals.json"
    tasks_path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    animals_path.write_text(json.dumps({"animals": animals or {}}), encoding="utf-8")
    return tasks_path, animals_path


def load(world, tmp_path, tasks, animals=None):
    return T.load_tasks(world, *write_files(tmp_path, tasks, animals))


def entry(task_id="t1", type="country", prompt="Find it.", targets=("country:France",),
          difficulty=2):
    return {"id": task_id, "type": type, "prompt": prompt, "targets": list(targets),
            "difficulty": difficulty}


def country_task(world, task_id, *names, type="country", level=2):
    refs = [f"country:{n}" for n in names]
    return T.Task(task_id, type, f"Find {names[0]}.", refs, level,
                  [world.resolve(r) for r in refs])


# ---- load_tasks: the good path ---------------------------------------------------
def test_load_tasks_reads_a_valid_file(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("france", targets=["country:France"], difficulty=1),
        entry("nile", type="feature", prompt="Where is the Nile?", targets=["river:Nile"],
              difficulty=3),
    ])
    assert problems == []
    assert ids(tasks) == ["france", "nile"]
    france, nile = tasks
    assert (france.type, france.prompt, france.difficulty) == ("country", "Find it.", 1)
    assert france.targets == ["country:France"]
    assert france.areas == [world.find("country:France")]
    assert nile.areas == [world.find("river:Nile")]
    assert nile.type == "feature" and nile.difficulty == 3


def test_load_tasks_resolves_targets_case_insensitively_and_by_code(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("a", targets=["COUNTRY:france"]), entry("b", targets=["country:FRA"]),
    ])
    assert problems == []
    assert tasks[0].areas == tasks[1].areas == [world.find("country:France")]


def test_load_tasks_empty_file_gives_no_tasks(world, tmp_path):
    assert load(world, tmp_path, []) == ([], [])


def test_load_tasks_strips_the_prompt(world, tmp_path):
    tasks, _ = load(world, tmp_path, [entry(prompt="  Find France.  ")])
    assert tasks[0].prompt == "Find France."


def test_load_tasks_gives_a_missing_id_a_number(world, tmp_path):
    first, second = entry("x"), entry()
    del second["id"]
    tasks, problems = load(world, tmp_path, [first, second])
    assert problems == []
    assert ids(tasks) == ["x", "task-2"]


def test_load_tasks_merges_duplicate_targets(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry(targets=["country:France", "country:FRA", "country:france", "country:Spain"]),
    ])
    assert problems == []
    assert tasks[0].areas == [world.find("country:France"), world.find("country:Spain")]


# ---- load_tasks: animals -----------------------------------------------------------
ANIMALS = {
    "lion": {"name": "lions", "areas": ["country:Kenya", "country:Tanzania"]},
    "kangaroo": {"name": "kangaroos", "areas": ["country:Australia"]},
}


def test_animal_target_expands_to_the_animals_areas(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("lions", type="animal", prompt="Where do lions live?", targets=["animal:lion"]),
    ], ANIMALS)
    assert problems == []
    assert tasks[0].targets == ["animal:lion"]
    assert tasks[0].areas == [world.find("country:Kenya"), world.find("country:Tanzania")]


def test_animal_reference_is_case_insensitive(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("lions", type="animal", targets=["Animal:LION"]),
    ], ANIMALS)
    assert problems == []
    assert len(tasks[0].areas) == 2


def test_animal_and_plain_targets_can_be_mixed_without_duplicates(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("mix", type="animal",
              targets=["animal:lion", "country:Kenya", "animal:kangaroo", "country:Uganda"]),
    ], ANIMALS)
    assert problems == []
    names = [a.name for a in tasks[0].areas]
    assert names == ["Kenya", "Tanzania", "Australia", "Uganda"]


def test_unknown_animal_is_reported_and_the_task_skipped(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("dragons", type="animal", targets=["animal:dragon"]),
        entry("ok"),
    ], ANIMALS)
    assert ids(tasks) == ["ok"]
    assert any("dragons" in p and "unknown animal" in p for p in problems)
    assert any("dragons" in p and "no valid targets" in p for p in problems)


def test_unknown_animal_is_trimmed_when_another_target_is_valid(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("half", type="animal", targets=["animal:dragon", "animal:kangaroo"]),
    ], ANIMALS)
    assert ids(tasks) == ["half"]
    assert tasks[0].areas == [world.find("country:Australia")]
    assert len(problems) == 1 and "unknown animal" in problems[0]


def test_unknown_area_in_the_animal_file_is_reported_and_trimmed(world, tmp_path):
    animals = {"yeti": {"name": "yetis", "areas": ["country:Nepal", "country:Shangri-La"]}}
    tasks, problems = load(world, tmp_path, [
        entry("yeti", type="animal", targets=["animal:yeti"]),
    ], animals)
    assert len(problems) == 1
    assert "yeti" in problems[0] and "Shangri-La" in problems[0]
    assert tasks[0].areas == [world.find("country:Nepal")]


def test_load_animals_returns_names_and_areas(world, tmp_path):
    _, animals_path = write_files(tmp_path, [], {
        "Lion": {"name": "lions", "areas": ["country:Kenya", "country:kenya"]},
        "emu": {"areas": ["country:Australia"]},
    })
    animals, problems = T.load_animals(world, animals_path)
    assert problems == []
    assert set(animals) == {"lion", "emu"}
    assert animals["lion"] == {"name": "lions", "areas": [world.find("country:Kenya")]}
    assert animals["emu"]["name"] == "emu"   # falls back to the key


# ---- load_tasks: validation ------------------------------------------------------------
def test_unknown_area_alone_skips_the_task(world, tmp_path):
    tasks, problems = load(world, tmp_path, [entry("bad", targets=["country:Atlantis"]),
                                             entry("ok")])
    assert ids(tasks) == ["ok"]
    assert any("'bad'" in p and "unknown area" in p and "Atlantis" in p for p in problems)
    assert any("'bad'" in p and "skipped" in p for p in problems)


def test_unknown_area_is_trimmed_when_another_target_is_valid(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("half", targets=["country:Atlantis", "country:Spain"]),
    ])
    assert ids(tasks) == ["half"]
    assert tasks[0].areas == [world.find("country:Spain")]
    assert len(problems) == 1 and "Atlantis" in problems[0]


@pytest.mark.parametrize("bad_type", ["river", "Country", "", None, 3])
def test_bad_type_is_reported_and_skipped(world, tmp_path, bad_type):
    tasks, problems = load(world, tmp_path, [entry("bad", type=bad_type), entry("ok")])
    assert ids(tasks) == ["ok"]
    assert len(problems) == 1
    assert "'bad'" in problems[0] and "type" in problems[0]


@pytest.mark.parametrize("bad_difficulty", [0, 4, -1, "1", "easy", None, 1.5])
def test_bad_difficulty_is_reported_and_skipped(world, tmp_path, bad_difficulty):
    tasks, problems = load(world, tmp_path, [entry("bad", difficulty=bad_difficulty),
                                             entry("ok")])
    assert ids(tasks) == ["ok"]
    assert len(problems) == 1
    assert "'bad'" in problems[0] and "difficulty" in problems[0]


def test_missing_fields_are_reported_and_skipped(world, tmp_path):
    tasks, problems = load(world, tmp_path, [{"id": "bare"}, entry("ok")])
    assert ids(tasks) == ["ok"]
    assert len(problems) == 1 and "'bare'" in problems[0]


def test_duplicate_id_keeps_the_first_task_only(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("same", targets=["country:France"]),
        entry("same", targets=["country:Spain"]),
        entry("other"),
    ])
    assert ids(tasks) == ["same", "other"]
    assert tasks[0].areas == [world.find("country:France")]
    assert len(problems) == 1
    assert "'same'" in problems[0] and "duplicate" in problems[0]


@pytest.mark.parametrize("prompt", ["", "   ", None])
def test_empty_prompt_is_reported_and_skipped(world, tmp_path, prompt):
    tasks, problems = load(world, tmp_path, [entry("bad", prompt=prompt), entry("ok")])
    assert ids(tasks) == ["ok"]
    assert len(problems) == 1
    assert "'bad'" in problems[0] and "prompt" in problems[0]


@pytest.mark.parametrize("targets", [[], None])
def test_no_targets_is_reported_and_skipped(world, tmp_path, targets):
    bad = entry("bad")
    bad["targets"] = targets
    tasks, problems = load(world, tmp_path, [bad, entry("ok")])
    assert ids(tasks) == ["ok"]
    assert len(problems) == 1 and "no valid targets" in problems[0]


def test_every_kind_of_mistake_at_once_does_not_raise(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("ok-1"),
        entry("unknown-area", targets=["country:Atlantis"]),
        entry("unknown-animal", type="animal", targets=["animal:dragon"]),
        entry("bad-type", type="quiz"),
        entry("bad-difficulty", difficulty=7),
        entry("ok-1"),
        entry("no-prompt", prompt=""),
        entry("ok-2", type="feature", targets=["river:Nile"]),
    ], ANIMALS)
    assert ids(tasks) == ["ok-1", "ok-2"]
    for name in ("unknown-area", "unknown-animal", "bad-type", "bad-difficulty", "ok-1",
                 "no-prompt"):
        assert any(repr(name) in p for p in problems), name
    assert all(isinstance(p, str) and p for p in problems)


# ---- load_tasks: small countries at level 1 ---------------------------------------------
@pytest.mark.parametrize("small", ["Luxembourg", "Malta"])
def test_small_country_is_excluded_from_level_1(world, tmp_path, small):
    assert world.find(f"country:{small}").size_deg < T.EASY_MIN_SIZE_DEG
    tasks, problems = load(world, tmp_path, [
        entry("small", targets=[f"country:{small}"], difficulty=1),
        entry("big", targets=["country:France"], difficulty=1),
    ])
    assert ids(tasks) == ["big"]
    assert len(problems) == 1
    assert "'small'" in problems[0] and "too small" in problems[0]


@pytest.mark.parametrize("small", ["Luxembourg", "Malta"])
@pytest.mark.parametrize("difficulty", [2, 3])
def test_small_country_is_kept_at_higher_levels(world, tmp_path, small, difficulty):
    tasks, problems = load(world, tmp_path, [
        entry("small", targets=[f"country:{small}"], difficulty=difficulty),
    ])
    assert problems == []
    assert ids(tasks) == ["small"]
    assert tasks[0].difficulty == difficulty


def test_big_countries_pass_the_level_1_size_check(world, tmp_path):
    names = ["France", "Brazil", "Russia", "Australia", "Egypt", "Iceland"]
    for name in names:
        assert world.find(f"country:{name}").size_deg >= T.EASY_MIN_SIZE_DEG, name
    tasks, problems = load(world, tmp_path, [
        entry(n, targets=[f"country:{n}"], difficulty=1) for n in names
    ])
    assert problems == []
    assert ids(tasks) == names


def test_level_1_task_is_kept_if_any_target_country_is_big_enough(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("mixed", targets=["country:Luxembourg", "country:France"], difficulty=1),
    ])
    assert problems == [] and ids(tasks) == ["mixed"]


def test_level_1_size_check_only_applies_to_country_tasks(world, tmp_path):
    tasks, problems = load(world, tmp_path, [
        entry("lake", type="feature", targets=["lake:Lake Victoria"], difficulty=1),
        entry("animal", type="animal", targets=["country:Malta"], difficulty=1),
    ])
    assert problems == []
    assert ids(tasks) == ["lake", "animal"]


# ---- the real bundled files ---------------------------------------------------------------
def test_bundled_task_files_are_valid(world):
    tasks, problems = T.load_tasks(world)
    assert problems == []
    per_level = Counter(t.difficulty for t in tasks)
    for level in (1, 2, 3):
        assert per_level[level] >= 10, f"level {level} has only {per_level[level]} tasks"
    assert set(per_level) <= {1, 2, 3}
    task_ids = ids(tasks)
    assert len(task_ids) == len(set(task_ids))
    for task in tasks:
        assert task.type in ("country", "feature", "animal", "landmark"), task.id
        assert task.prompt, task.id
        assert task.areas, task.id


def test_bundled_task_file_has_no_duplicate_ids_in_the_raw_json():
    # load_tasks drops duplicates, so look at the file itself as well.
    from geoquiz.paths import resource_path

    with open(resource_path(T.TASKS_FILE), encoding="utf-8") as fh:
        raw = json.load(fh)["tasks"]
    counts = Counter(e.get("id") for e in raw)
    assert [i for i, n in counts.items() if n > 1] == []
    assert None not in counts


def test_bundled_level_1_country_tasks_are_big_enough_to_click(world):
    tasks, _ = T.load_tasks(world)
    for task in tasks:
        if task.difficulty == 1 and task.type == "country":
            assert max(a.size_deg for a in task.areas) >= T.EASY_MIN_SIZE_DEG, task.id


# ---- Progress -------------------------------------------------------------------------------
def test_progress_starts_empty(tmp_path):
    p = T.Progress(tmp_path / "progress.json")
    assert p.tasks == {} and p.best == {}
    assert p.seen("anything") == 0
    assert p.missed_last_time("anything") is False
    assert p.best_for(1) == 0


def test_progress_record_counts_seen_and_missed():
    p = T.Progress()
    p.record("a", missed=True)
    p.record("a", missed=True)
    p.record("a", missed=False)
    p.record("b", missed=False)
    assert p.seen("a") == 3 and p.seen("b") == 1
    assert p.tasks["a"]["missed"] == 2 and p.tasks["b"]["missed"] == 0
    assert p.missed_last_time("a") is False
    assert p.missed_last_time("b") is False


def test_progress_missed_last_time_follows_the_latest_result():
    p = T.Progress()
    p.record("a", missed=True)
    assert p.missed_last_time("a") is True
    p.record("a", missed=False)
    assert p.missed_last_time("a") is False
    p.record("a", missed=True)
    assert p.missed_last_time("a") is True


def test_progress_round_trips_through_save_and_reload(tmp_path):
    path = tmp_path / "progress.json"
    p = T.Progress(path)
    p.record("a", missed=True)
    p.record("a", missed=False)
    p.record("b", missed=True)
    p.record_round(1, 7)
    p.record_round(3, 2)
    p.save()
    assert path.exists()
    assert not path.with_suffix(".tmp").exists()

    q = T.Progress(path)
    assert q.tasks == p.tasks and q.best == p.best
    assert q.seen("a") == 2 and q.seen("b") == 1
    assert q.missed_last_time("b") is True and q.missed_last_time("a") is False
    assert q.best_for(1) == 7 and q.best_for(3) == 2 and q.best_for(2) == 0


def test_progress_save_overwrites_and_keeps_counting_after_reload(tmp_path):
    path = tmp_path / "progress.json"
    p = T.Progress(path)
    p.record("a", missed=False)
    p.save()
    q = T.Progress(path)
    q.record("a", missed=True)
    q.save()
    r = T.Progress(path)
    assert r.seen("a") == 2 and r.missed_last_time("a") is True


def test_progress_file_is_plain_json(tmp_path):
    path = tmp_path / "progress.json"
    p = T.Progress(path)
    p.record("a", missed=True)
    p.record_round(2, 9)
    p.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"language": "", "tasks": {"a": {"seen": 1, "missed": 1, "last_missed": True}},
                    "best": {"2": 9}}


def test_progress_remembers_the_chosen_language(tmp_path):
    path = tmp_path / "progress.json"
    p = T.Progress(path)
    assert p.language == ""
    p.language = "pl"
    p.save()
    assert T.Progress(path).language == "pl"


def test_progress_without_a_path_does_not_save_anywhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = T.Progress()
    p.record("a", missed=True)
    p.save()
    assert list(tmp_path.iterdir()) == []


def test_progress_save_into_a_missing_folder_does_not_raise(tmp_path):
    p = T.Progress(tmp_path / "no-such-folder" / "progress.json")
    p.record("a", missed=True)
    p.save()
    assert p.seen("a") == 1


@pytest.mark.parametrize("content", [
    b"",
    b"this is not json {{{",
    b'{"tasks": {"a": {"seen": 1',     # truncated while writing
    b"\xff\xfe\x00\x01\x80garbage",    # not even text
    b"[]",
    b"[1, 2, 3]",
    b'"hello"',
    b"42",
    b"null",
])
def test_progress_survives_a_corrupt_file(tmp_path, content):
    path = tmp_path / "progress.json"
    path.write_bytes(content)
    p = T.Progress(path)
    assert p.tasks == {} and p.best == {}
    # ...and is fully usable afterwards.
    p.record("a", missed=True)
    p.record_round(1, 3)
    p.save()
    assert T.Progress(path).seen("a") == 1


@pytest.mark.parametrize("content", [
    '{"tasks": null, "best": null}',
    '{"tasks": 5}',
    '{"tasks": {}, "best": 3}',
])
def test_progress_survives_valid_json_of_the_wrong_shape(tmp_path, content):
    path = tmp_path / "progress.json"
    path.write_text(content, encoding="utf-8")
    p = T.Progress(path)
    assert p.seen("a") == 0
    assert p.best_for(1) == 0
    p.record("a", missed=False)
    p.record_round(1, 4)
    assert p.seen("a") == 1 and p.best_for(1) == 4


def test_progress_file_with_only_some_keys(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text('{"best": {"2": 6}}', encoding="utf-8")
    p = T.Progress(path)
    assert p.tasks == {} and p.best_for(2) == 6


def test_record_round_keeps_the_best():
    p = T.Progress()
    assert p.best_for(1) == 0
    p.record_round(1, 4)
    assert p.best_for(1) == 4
    p.record_round(1, 9)
    assert p.best_for(1) == 9
    p.record_round(1, 6)
    assert p.best_for(1) == 9
    p.record_round(1, 0)
    assert p.best_for(1) == 9


def test_record_round_keeps_levels_apart():
    p = T.Progress()
    p.record_round(1, 10)
    p.record_round(2, 3)
    assert (p.best_for(1), p.best_for(2), p.best_for(3)) == (10, 3, 0)


# ---- select_round -----------------------------------------------------------------------------
@pytest.mark.parametrize("level", [1, 2, 3])
def test_round_has_only_tasks_of_the_requested_level(level):
    tasks = make_tasks({1: 15, 2: 15, 3: 15})
    for seed in range(20):
        chosen = T.select_round(tasks, level, T.Progress(), random.Random(seed))
        assert len(chosen) == 10
        assert {t.difficulty for t in chosen} == {level}


def test_round_has_only_tasks_of_the_requested_level_without_progress():
    tasks = make_tasks({1: 15, 2: 15, 3: 15})
    chosen = T.select_round(tasks, 2, None, random.Random(1))
    assert len(chosen) == 10 and {t.difficulty for t in chosen} == {2}


@pytest.mark.parametrize("with_progress", [False, True])
def test_no_task_is_repeated_within_a_round(with_progress):
    tasks = make_tasks({1: 12, 2: 30})
    for seed in range(30):
        progress = T.Progress() if with_progress else None
        if progress:
            for t in tasks[::3]:
                progress.record(t.id, missed=True)
        chosen = T.select_round(tasks, 1, progress, random.Random(seed))
        assert len(set(ids(chosen))) == len(chosen) == 10


def test_round_length_is_ten():
    assert T.ROUND_LENGTH == 10
    tasks = make_tasks({1: 40})
    assert len(T.select_round(tasks, 1, T.Progress(), random.Random(0))) == 10
    assert len(T.select_round(tasks, 1, None, random.Random(0))) == 10


@pytest.mark.parametrize("pool_size", [0, 1, 4, 9, 10])
@pytest.mark.parametrize("with_progress", [False, True])
def test_round_is_shorter_when_the_pool_is_smaller(pool_size, with_progress):
    tasks = make_tasks({1: pool_size, 2: 20})
    progress = T.Progress() if with_progress else None
    chosen = T.select_round(tasks, 1, progress, random.Random(3))
    assert sorted(ids(chosen)) == sorted(t.id for t in tasks if t.difficulty == 1)


def test_level_without_tasks_gives_an_empty_round():
    assert T.select_round(make_tasks({1: 5}), 3, T.Progress(), random.Random(0)) == []
    assert T.select_round([], 1) == []


def test_count_can_be_changed():
    tasks = make_tasks({1: 20})
    assert len(T.select_round(tasks, 1, T.Progress(), random.Random(0), count=3)) == 3
    assert len(T.select_round(tasks, 1, None, random.Random(0), count=3)) == 3


def test_selection_does_not_change_the_task_list():
    tasks = make_tasks({1: 20, 2: 5})
    before = list(tasks)
    T.select_round(tasks, 1, T.Progress(), random.Random(0))
    assert tasks == before


@pytest.mark.parametrize("with_progress", [False, True])
def test_same_seed_gives_the_same_round(with_progress):
    tasks = make_tasks({1: 30})

    def pick(seed):
        progress = T.Progress() if with_progress else None
        if progress:
            progress.record("L1-03", missed=True)
            progress.record("L1-07", missed=False)
        return ids(T.select_round(tasks, 1, progress, random.Random(seed)))

    for seed in (0, 1, 42):
        assert pick(seed) == pick(seed)


@pytest.mark.parametrize("with_progress", [False, True])
def test_different_seeds_give_different_rounds(with_progress):
    tasks = make_tasks({1: 30})
    rounds = set()
    for seed in range(10):
        progress = T.Progress() if with_progress else None
        rounds.add(tuple(ids(T.select_round(tasks, 1, progress, random.Random(seed)))))
    assert len(rounds) == 10


def test_order_is_shuffled_not_file_order():
    tasks = make_tasks({1: 10})
    orders = {tuple(ids(T.select_round(tasks, 1, T.Progress(), random.Random(s))))
              for s in range(10)}
    assert len(orders) > 1
    assert all(sorted(o) == ids(tasks) for o in orders)


def test_without_an_rng_it_still_works():
    chosen = T.select_round(make_tasks({1: 30}), 1, T.Progress())
    assert len(set(ids(chosen))) == 10


@pytest.mark.parametrize("missed_count", [1, 3, 5])
def test_all_missed_tasks_are_included_when_there_are_at_most_five(missed_count):
    tasks = make_tasks({1: 40})
    for seed in range(25):
        progress = T.Progress()
        missed = ids(random.Random(100 + seed).sample(tasks, missed_count))
        for task_id in missed:
            progress.record(task_id, missed=True)
        chosen = ids(T.select_round(tasks, 1, progress, random.Random(seed)))
        assert set(missed) <= set(chosen)
        assert len(chosen) == 10


def test_at_most_five_missed_tasks_when_there_are_more():
    tasks = make_tasks({1: 40})
    missed = set(ids(tasks[:12]))
    included = set()
    for seed in range(40):
        progress = T.Progress()
        for task_id in missed:
            progress.record(task_id, missed=True)
        chosen = ids(T.select_round(tasks, 1, progress, random.Random(seed)))
        review = missed & set(chosen)
        assert len(review) == T.MAX_REVIEW_TASKS == 5
        assert len(chosen) == 10
        included |= review
    # Which five are reviewed varies from round to round.
    assert len(included) > 5


def test_max_review_can_be_changed():
    tasks = make_tasks({1: 40})
    progress = T.Progress()
    for t in tasks[:12]:
        progress.record(t.id, missed=True)
    chosen = ids(T.select_round(tasks, 1, progress, random.Random(0), max_review=2))
    assert len(set(chosen) & set(ids(tasks[:12]))) == 2
    assert len(chosen) == 10


def test_missed_tasks_of_another_level_are_not_pulled_in():
    tasks = make_tasks({1: 20, 2: 20})
    progress = T.Progress()
    for t in tasks:
        if t.difficulty == 2:
            progress.record(t.id, missed=True)
    chosen = T.select_round(tasks, 1, progress, random.Random(0))
    assert {t.difficulty for t in chosen} == {1}


def test_task_answered_correctly_later_stops_being_preferred():
    tasks = make_tasks({1: 40})
    for seed in range(25):
        progress = T.Progress()
        progress.record("L1-00", missed=True)
        progress.record("L1-01", missed=True)
        assert "L1-00" in ids(T.select_round(tasks, 1, progress, random.Random(seed)))
        progress.record("L1-00", missed=False)
        chosen = ids(T.select_round(tasks, 1, progress, random.Random(seed)))
        # Now it is just a task seen twice, behind 38 unseen ones.
        assert "L1-00" not in chosen
        assert "L1-01" in chosen


def test_unseen_tasks_come_before_played_ones():
    tasks = make_tasks({1: 25})
    played = set(ids(tasks[:15]))
    for seed in range(25):
        progress = T.Progress()
        for task_id in played:
            progress.record(task_id, missed=False)
        chosen = set(ids(T.select_round(tasks, 1, progress, random.Random(seed))))
        assert chosen == set(ids(tasks[15:]))   # exactly the ten unseen ones


def test_least_seen_tasks_fill_the_rest():
    tasks = make_tasks({1: 20})
    progress = T.Progress()
    for i, t in enumerate(tasks):
        seen = 3 if i < 6 else 2 if i < 12 else 1    # 6 x thrice, 6 x twice, 8 x once
        for _ in range(seen):
            progress.record(t.id, missed=False)
    for seed in range(25):
        chosen = set(ids(T.select_round(tasks, 1, progress, random.Random(seed))))
        assert set(ids(tasks[12:])) <= chosen               # all eight seen once
        assert len(chosen & set(ids(tasks[6:12]))) == 2     # two of those seen twice
        assert not chosen & set(ids(tasks[:6]))             # none of those seen thrice


def test_missed_tasks_come_first_then_unseen_then_seen():
    tasks = make_tasks({1: 30})
    progress = T.Progress()
    missed = ids(tasks[:3])
    for task_id in missed:
        for _ in range(4):
            progress.record(task_id, missed=True)     # seen most often of all
    for t in tasks[3:25]:
        progress.record(t.id, missed=False)
    unseen = ids(tasks[25:])
    for seed in range(25):
        chosen = set(ids(T.select_round(tasks, 1, progress, random.Random(seed))))
        assert set(missed) <= chosen
        assert set(unseen) <= chosen
        assert len(chosen) == 10


def test_playing_rounds_eventually_covers_every_task():
    tasks = make_tasks({1: 30})
    progress = T.Progress()
    rng = random.Random(5)
    seen = []
    for _ in range(3):
        chosen = T.select_round(tasks, 1, progress, rng)
        for t in chosen:
            progress.record(t.id, missed=False)
        seen += ids(chosen)
    assert sorted(seen) == ids(tasks)   # 3 rounds of 10: each task exactly once


def test_selection_works_with_progress_loaded_from_disk(tmp_path):
    path = tmp_path / "progress.json"
    tasks = make_tasks({1: 40})
    p = T.Progress(path)
    for task_id in ("L1-05", "L1-06"):
        p.record(task_id, missed=True)
    p.save()
    chosen = ids(T.select_round(tasks, 1, T.Progress(path), random.Random(0)))
    assert {"L1-05", "L1-06"} <= set(chosen)


# ---- Round ----------------------------------------------------------------------------------
def test_new_round_state(world):
    r = T.Round(world, [country_task(world, "fr", "France"), country_task(world, "jp", "Japan")])
    assert r.index == 0 and r.task.id == "fr"
    assert not r.finished and not r.hint_active and not r.solved
    assert r.wrong_attempts == 0 and r.stars == 0
    assert r.results == [None, None]


def test_correct_first_try_earns_a_star(world, px):
    r = T.Round(world, [country_task(world, "fr", "France")])
    outcome = r.click(*PARIS, px)
    assert outcome.kind == "correct"
    assert outcome.star is True
    assert outcome.hit is world.find("country:France")
    assert outcome.wrong_attempts == 0
    assert outcome.hint_started is False
    assert r.solved and r.stars == 1 and r.results == [True]


def test_correct_after_one_or_two_misses_still_earns_a_star(world, px):
    for misses in (1, 2):
        r = T.Round(world, [country_task(world, "fr", "France")])
        for _ in range(misses):
            assert r.click(*BRASILIA, px).kind == "wrong"
        assert not r.hint_active
        outcome = r.click(*PARIS, px)
        assert outcome.kind == "correct" and outcome.star is True
        assert outcome.wrong_attempts == misses
        assert r.stars == 1


def test_third_wrong_click_starts_the_hint(world, px):
    assert T.MAX_WRONG_ATTEMPTS == 3
    r = T.Round(world, [country_task(world, "fr", "France")])
    first = r.click(*BRASILIA, px)
    second = r.click(*TOKYO, px)
    assert (first.wrong_attempts, second.wrong_attempts) == (1, 2)
    assert not first.hint_started and not second.hint_started
    assert not r.hint_active
    third = r.click(*BRASILIA, px)
    assert third.kind == "wrong"
    assert third.hint_started is True
    assert third.wrong_attempts == 3
    assert r.hint_active is True


def test_close_clicks_count_as_wrong_attempts_too(world, px):
    r = T.Round(world, [country_task(world, "fr", "France")])
    kinds = [r.click(13.4, 52.52, px).kind for _ in range(3)]   # Berlin
    assert kinds == ["close", "close", "close"]
    assert r.hint_active and r.wrong_attempts == 3


def test_correct_click_after_the_hint_gives_no_star(world, px):
    r = T.Round(world, [country_task(world, "fr", "France")])
    for _ in range(3):
        r.click(*BRASILIA, px)
    outcome = r.click(*PARIS, px)
    assert outcome.kind == "correct"
    assert outcome.star is False
    assert outcome.wrong_attempts == 3
    assert r.solved and r.stars == 0 and r.results == [False]


def test_there_is_no_fail_state(world, px):
    r = T.Round(world, [country_task(world, "fr", "France"), country_task(world, "jp", "Japan")])
    outcomes = [r.click(*BRASILIA, px) for _ in range(12)]
    assert all(o is not None and o.kind == "wrong" for o in outcomes)
    assert [o.wrong_attempts for o in outcomes] == list(range(1, 13))
    # The hint starts exactly once, on the third miss.
    assert [o.hint_started for o in outcomes] == [False, False, True] + [False] * 9
    assert r.hint_active and not r.solved and not r.finished
    assert r.index == 0 and r.task.id == "fr"
    # ...and the task can still be solved.
    assert r.click(*PARIS, px).kind == "correct"


def test_clicking_again_after_the_task_is_solved_returns_none(world, px):
    r = T.Round(world, [country_task(world, "fr", "France"), country_task(world, "jp", "Japan")])
    assert r.click(*PARIS, px).kind == "correct"
    assert r.click(*PARIS, px) is None
    assert r.click(*BRASILIA, px) is None
    assert r.wrong_attempts == 0 and r.stars == 1 and r.results == [True, None]


def test_advance_moves_on_and_resets_the_attempt_state(world, px):
    r = T.Round(world, [country_task(world, "fr", "France"), country_task(world, "jp", "Japan")])
    for _ in range(3):
        r.click(*BRASILIA, px)
    r.click(*PARIS, px)
    assert r.advance() is True
    assert r.task.id == "jp" and r.index == 1
    assert r.wrong_attempts == 0 and not r.hint_active and not r.solved
    outcome = r.click(*TOKYO, px)
    assert outcome.kind == "correct" and outcome.star is True


def test_advance_returns_false_after_the_last_task_and_stars_are_counted(world, px):
    tasks = [country_task(world, "fr", "France"), country_task(world, "jp", "Japan"),
             country_task(world, "br", "Brazil")]
    r = T.Round(world, tasks)
    assert r.click(*PARIS, px).star                    # star
    assert r.advance() is True
    for _ in range(3):
        r.click(*PARIS, px)                            # three misses, hint
    assert r.click(*TOKYO, px).star is False           # no star
    assert r.advance() is True
    r.click(*PARIS, px)                                # one miss
    assert r.click(*BRASILIA, px).star                 # star
    assert not r.finished
    assert r.advance() is False
    assert r.finished and r.task is None
    assert r.stars == 2
    assert r.results == [True, False, True]


def test_click_after_the_round_is_over_returns_none(world, px):
    r = T.Round(world, [country_task(world, "fr", "France")])
    r.click(*PARIS, px)
    assert r.advance() is False
    assert r.click(*PARIS, px) is None


def test_empty_round_is_finished_at_once(world, px):
    r = T.Round(world, [])
    assert r.finished and r.task is None and r.stars == 0
    assert r.click(*PARIS, px) is None


def test_skipped_task_earns_no_star(world, px):
    r = T.Round(world, [country_task(world, "fr", "France"), country_task(world, "jp", "Japan")])
    assert r.advance() is True
    r.click(*TOKYO, px)
    assert r.advance() is False
    assert r.stars == 1 and r.results == [None, True]


def test_progress_records_a_clean_answer_as_not_missed(world, px, tmp_path):
    progress = T.Progress(tmp_path / "progress.json")
    r = T.Round(world, [country_task(world, "fr", "France")], progress, level=2)
    r.click(*PARIS, px)
    assert progress.seen("fr") == 1
    assert progress.missed_last_time("fr") is False
    assert progress.tasks["fr"]["missed"] == 0


@pytest.mark.parametrize("misses", [1, 2, 3, 5])
def test_progress_marks_a_task_missed_after_any_wrong_attempt(world, px, tmp_path, misses):
    progress = T.Progress(tmp_path / "progress.json")
    r = T.Round(world, [country_task(world, "fr", "France")], progress, level=2)
    for _ in range(misses):
        r.click(*BRASILIA, px)
    assert progress.seen("fr") == 0        # nothing recorded until it is solved
    r.click(*PARIS, px)
    assert progress.seen("fr") == 1
    assert progress.missed_last_time("fr") is True
    assert progress.tasks["fr"]["missed"] == 1


def test_progress_counts_a_close_click_as_a_miss(world, px, tmp_path):
    progress = T.Progress(tmp_path / "progress.json")
    r = T.Round(world, [country_task(world, "fr", "France")], progress)
    assert r.click(13.4, 52.52, px).kind == "close"
    r.click(*PARIS, px)
    assert progress.missed_last_time("fr") is True


def test_progress_is_recorded_once_per_task(world, px, tmp_path):
    progress = T.Progress(tmp_path / "progress.json")
    r = T.Round(world, [country_task(world, "fr", "France")], progress)
    r.click(*PARIS, px)
    r.click(*PARIS, px)
    r.click(*PARIS, px)
    assert progress.seen("fr") == 1


def test_round_saves_progress_to_disk_as_it_goes(world, px, tmp_path):
    path = tmp_path / "progress.json"
    tasks = [country_task(world, "fr", "France"), country_task(world, "jp", "Japan")]
    r = T.Round(world, tasks, T.Progress(path), level=3)
    r.click(*BRASILIA, px)
    r.click(*PARIS, px)
    on_disk = T.Progress(path)
    assert on_disk.seen("fr") == 1 and on_disk.missed_last_time("fr") is True
    assert on_disk.best_for(3) == 0        # the round is not over yet
    r.advance()
    r.click(*TOKYO, px)
    assert r.advance() is False
    on_disk = T.Progress(path)
    assert on_disk.seen("jp") == 1 and on_disk.missed_last_time("jp") is False
    assert on_disk.best_for(3) == 2


def test_finished_round_keeps_the_best_score(world, px, tmp_path):
    path = tmp_path / "progress.json"
    tasks = [country_task(world, "fr", "France"), country_task(world, "jp", "Japan")]

    def play(first_click):
        r = T.Round(world, tasks, T.Progress(path), level=1)
        for _ in range(3):
            r.click(*first_click, px)      # hint on the first task unless correct
        r.click(*PARIS, px)
        r.advance()
        r.click(*TOKYO, px)
        r.advance()
        return r.stars

    assert play(PARIS) == 2
    assert T.Progress(path).best_for(1) == 2
    assert play(BRASILIA) == 1
    assert T.Progress(path).best_for(1) == 2   # a worse round does not lower it


def test_missed_task_comes_back_in_the_next_round(world, px, tmp_path):
    progress = T.Progress(tmp_path / "progress.json")
    pool = make_tasks({2: 40})
    france = country_task(world, "fr", "France", level=2)
    pool.append(france)
    r = T.Round(world, [france], progress, level=2)
    r.click(*BRASILIA, px)
    r.click(*PARIS, px)
    for seed in range(15):
        assert "fr" in ids(T.select_round(pool, 2, progress, random.Random(seed)))


def test_round_works_without_progress(world, px):
    r = T.Round(world, [country_task(world, "fr", "France")])
    r.click(*BRASILIA, px)
    assert r.click(*PARIS, px).kind == "correct"
    assert r.advance() is False


@pytest.mark.parametrize("lon, lat, country", [
    (37.9, 0.0, "Kenya"), (35.0, -6.0, "Tanzania"), (25.0, -29.0, "South Africa"),
])
def test_animal_task_accepts_a_click_in_any_listed_country(world, px, tmp_path, lon, lat,
                                                           country):
    animals = {"lion": {"name": "lions",
                        "areas": ["country:Kenya", "country:Tanzania", "country:South Africa"]}}
    tasks, problems = load(world, tmp_path, [
        entry("lions", type="animal", prompt="Where do lions live?", targets=["animal:lion"]),
    ], animals)
    assert problems == []
    r = T.Round(world, tasks)
    outcome = r.click(lon, lat, px)
    assert outcome.kind == "correct" and outcome.star
    assert outcome.hit is world.find(f"country:{country}")


def test_animal_task_rejects_a_country_that_is_not_listed(world, px):
    task = country_task(world, "lions", "Kenya", "Tanzania", "South Africa", type="animal")
    r = T.Round(world, [task])
    assert r.click(*PARIS, px).kind == "wrong"
    assert r.click(*BRASILIA, px).kind == "wrong"
    # Uganda borders Kenya and Tanzania: close, but not correct.
    assert r.click(32.4, 1.3, 16 * px).kind == "close"


def test_multi_target_task_reports_the_country_actually_clicked(world, px):
    # Exact hits win: Tanzania is listed second but is the one under the click.
    task = country_task(world, "lions", "Kenya", "Tanzania", type="animal")
    outcome = T.Round(world, [task]).click(35.0, -6.0, px)
    assert outcome.hit is world.find("country:Tanzania")
