"""Animal and landmark questions: pictures, pins and the task file fields behind them."""
import json
from pathlib import Path

import pytest

from geoquiz import tasks as T

PICTURES = Path(__file__).resolve().parent.parent / "data" / "pictures"


@pytest.fixture(scope="module")
def real_tasks(world):
    tasks, problems = T.load_tasks(world)
    assert not problems
    return tasks


def picture_file(picture_id):
    for ext in (".jpg", ".png", ".webp"):
        if (PICTURES / (picture_id + ext)).exists():
            return PICTURES / (picture_id + ext)
    return None


def test_every_animal_and_landmark_task_has_a_picture(real_tasks):
    missing = [t.id for t in real_tasks if t.type in ("animal", "landmark")
               and (not t.picture or picture_file(t.picture) is None)]
    assert not missing, f"no picture for: {missing}"


def test_country_and_feature_tasks_have_no_picture(real_tasks):
    assert all(not t.picture for t in real_tasks if t.type in ("country", "feature"))


def test_animal_tasks_show_their_own_animal(real_tasks):
    by_id = {t.id: t for t in real_tasks}
    assert by_id["animal-lion"].picture == "lion"
    assert by_id["animal-european-bison"].picture == "european_bison"


def test_every_picture_has_a_source_and_a_free_licence(real_tasks):
    sources = json.loads((PICTURES / "sources.json").read_text(encoding="utf-8"))
    credits = json.loads((PICTURES / "credits.json").read_text(encoding="utf-8"))
    for picture_id in {t.picture for t in real_tasks if t.picture}:
        assert picture_id in sources, f"{picture_id} is not in sources.json"
        credit = credits.get(picture_id)
        assert credit, f"{picture_id} has no entry in credits.json"
        assert credit["author"] and credit["file"].startswith("File:")
        assert credit["licence"].lower().startswith(("cc", "public domain", "pd", "gfdl", "no restrictions", "attribution"))
    assert (PICTURES / "CREDITS.md").exists()


def test_landmark_pins_lie_in_one_of_the_answer_countries(real_tasks):
    landmarks = [t for t in real_tasks if t.type == "landmark"]
    assert len(landmarks) >= 28
    for task in landmarks:
        assert task.pin is not None, task.id
        # A coastal landmark may sit a hair outside the simplified coastline.
        assert any(area.hit(task.pin[0], task.pin[1], 0.3) for area in task.areas), task.id
        assert T.task_category(task) == "landmarks"


def test_bison_are_two_separate_questions(world, real_tasks):
    by_id = {t.id: t for t in real_tasks}
    american = by_id["animal-bison"]
    european = by_id["animal-european-bison"]
    assert [a.id for a in american.areas] == ["region:Great Plains"]
    assert sorted(a.id for a in european.areas) == ["country:Belarus", "country:Poland"]
    px = 1920 / 360
    assert T.Round(world, [european]).click(19.0, 52.0, px).kind == "correct"        # Poland
    assert T.Round(world, [american]).click(19.0, 52.0, px).kind != "correct"
    assert T.Round(world, [american]).click(-100.0, 42.0, px).kind == "correct"      # Nebraska
    assert T.Round(world, [european]).click(-100.0, 42.0, px).kind != "correct"


def write(tmp_path, tasks):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    animals = tmp_path / "animals.json"
    animals.write_text(json.dumps({"animals": {"lion": {"name": "lions", "areas": ["country:Kenya"]}}}),
                       encoding="utf-8")
    return path, animals


def test_loader_reads_picture_and_pin(world, tmp_path):
    path, animals = write(tmp_path, [
        {"id": "tower", "type": "landmark", "prompt": "Where?", "targets": ["country:France"],
         "difficulty": 2, "picture": "eiffel_tower", "pin": [2.29, 48.86]},
        {"id": "lions", "type": "animal", "prompt": "Where?", "targets": ["animal:lion"], "difficulty": 2},
        {"id": "plain", "type": "country", "prompt": "Where?", "targets": ["country:Spain"], "difficulty": 2},
    ])
    tasks, problems = T.load_tasks(world, path, animals)
    assert not problems
    tower, lions, plain = tasks
    assert tower.picture == "eiffel_tower" and tower.pin == (2.29, 48.86)
    assert lions.picture == "lion" and lions.pin is None
    assert plain.picture == "" and plain.pin is None


@pytest.mark.parametrize("bad_pin", ["Paris", [1], [1, 2, 3], [500, 10], [10, "x"], {"lon": 1}])
def test_loader_reports_a_bad_pin_and_keeps_the_task(world, tmp_path, bad_pin):
    path, animals = write(tmp_path, [
        {"id": "tower", "type": "landmark", "prompt": "Where?", "targets": ["country:France"],
         "difficulty": 2, "pin": bad_pin}])
    tasks, problems = T.load_tasks(world, path, animals)
    assert len(tasks) == 1 and tasks[0].pin is None
    assert len(problems) == 1 and "pin" in problems[0]
