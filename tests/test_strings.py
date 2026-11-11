"""Strings: the texts in data/strings.json, phrase rotation and area names."""
import json
import random

import pytest

from geoquiz.speech import Speaker
from geoquiz.strings import Strings


@pytest.fixture(scope="module")
def raw():
    from geoquiz.paths import resource_path

    with open(resource_path("data/strings.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def strings():
    return Strings.load(rng=random.Random(7))


# ---- the real file ---------------------------------------------------------------
def test_real_file_loads(strings):
    assert strings.language == "en"


def test_load_from_an_explicit_path(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"language": "pl", "ui": {"quit": "Koniec"}}), encoding="utf-8")
    s = Strings.load(path)
    assert s.language == "pl"
    assert s.ui("quit") == "Koniec"


def test_defaults_for_an_empty_file():
    s = Strings({})
    assert s.language == "en"


def test_ui_texts(strings):
    assert strings.ui("quit") == "Quit"
    assert strings.ui("best_score", stars=3, total=10) == "Best: 3 of 10"
    assert strings.ui("task_counter", number=2, total=10) == "2 of 10"


def test_speech_texts(strings):
    assert strings.speech("welcome") == "Hello! Pick a level to start."
    assert strings.speech("that_is", name="France") == "That is France."
    assert strings.speech("round_end_perfect", total=10) == "Amazing! You got all 10 stars!"


@pytest.mark.parametrize("key", ["praise", "close", "wrong", "hint", "after_hint"])
def test_feedback_phrases_are_lists_with_some_variety(raw, key):
    phrases = raw["speech"][key]
    assert isinstance(phrases, list) and len(phrases) >= 2
    assert len(set(phrases)) == len(phrases)
    assert all(isinstance(p, str) and p.strip() for p in phrases)


def test_real_file_placeholders_all_format(raw, strings):
    fmt = dict(stars=3, total=10, number=1, name="France", phrase="Oops.", that_is="That is X.",
               hint="Look!", zone="In the box.")
    for key in raw["ui"]:
        text = strings.ui(key, **fmt)
        assert "{" not in text and "}" not in text, key
    for key in raw["speech"]:
        for _ in range(3):
            text = strings.speech(key, **fmt)
            assert "{" not in text and "}" not in text, key


# ---- missing keys / bad formats ------------------------------------------------------
def test_missing_key_returns_the_key_itself(strings):
    assert strings.ui("no_such_key") == "no_such_key"
    assert strings.speech("no_such_key") == "no_such_key"
    assert strings.ui("no_such_key", stars=1) == "no_such_key"
    assert strings.speech("no_such_key", name="x") == "no_such_key"


def test_missing_sections_do_not_raise():
    s = Strings({})
    assert s.ui("quit") == "quit"
    assert s.speech("praise") == "praise"


def test_missing_format_argument_returns_the_raw_text(strings):
    assert strings.ui("best_score") == "Best: {stars} of {total}"
    assert strings.ui("best_score", stars=3) == "Best: {stars} of {total}"


def test_broken_format_string_does_not_raise():
    s = Strings({"ui": {"a": "Score {", "b": "Score {0}", "c": "100% {name"}})
    assert s.ui("a", stars=1) == "Score {"
    assert s.ui("b", stars=1) == "Score {0}"
    assert s.ui("c", name="x") == "100% {name"


def test_empty_phrase_list_gives_an_empty_string():
    assert Strings({"speech": {"praise": []}}).speech("praise") == ""


# ---- phrase rotation --------------------------------------------------------------------
@pytest.mark.parametrize("key", ["praise", "close", "wrong", "hint", "after_hint"])
@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_phrases_never_repeat_immediately(raw, key, seed):
    s = Strings(raw, random.Random(seed))
    said = [s.speech(key) for _ in range(60)]
    assert all(a != b for a, b in zip(said, said[1:]))
    assert set(said) == set(raw["speech"][key])


@pytest.mark.parametrize("key", ["praise", "close", "wrong", "hint", "after_hint"])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_phrase_is_used_before_any_repeats(raw, key, seed):
    phrases = raw["speech"][key]
    n = len(phrases)
    s = Strings(raw, random.Random(seed))
    said = [s.speech(key) for _ in range(n * 5)]
    for start in range(0, len(said), n):
        assert sorted(said[start:start + n]) == sorted(phrases)


def test_rotation_with_a_seed_is_deterministic(raw):
    def run(seed):
        s = Strings(raw, random.Random(seed))
        return [s.speech("praise") for _ in range(20)]

    assert run(1) == run(1)
    assert len({tuple(run(seed)) for seed in range(6)}) > 1


def test_rotation_is_independent_per_key(raw):
    s = Strings(raw, random.Random(0))
    n = len(raw["speech"]["praise"])
    said = []
    for _ in range(n):
        said.append(s.speech("praise"))
        s.speech("wrong")
        s.speech("close")
    assert sorted(said) == sorted(raw["speech"]["praise"])


def test_two_phrase_list_simply_alternates():
    for seed in range(10):
        s = Strings({"speech": {"k": ["A", "B"]}}, random.Random(seed))
        said = [s.speech("k") for _ in range(12)]
        assert said in (["A", "B"] * 6, ["B", "A"] * 6)


def test_single_phrase_list_repeats_without_raising():
    s = Strings({"speech": {"k": ["Only one"]}})
    assert [s.speech("k") for _ in range(3)] == ["Only one"] * 3


def test_picked_phrase_is_formatted():
    s = Strings({"speech": {"k": ["Hello {name}!", "Hi {name}!"]}}, random.Random(0))
    assert {s.speech("k", name="Tom") for _ in range(4)} == {"Hello Tom!", "Hi Tom!"}


# ---- area names -----------------------------------------------------------------------------
@pytest.mark.parametrize("ref, spoken", [
    ("country:United States of America", "the United States"),
    ("country:United Kingdom", "the United Kingdom"),
    ("country:Netherlands", "the Netherlands"),
    ("region:Sahara", "the Sahara desert"),
])
def test_area_name_uses_the_names_override(world, strings, ref, spoken):
    assert strings.area_name(world.resolve(ref)) == spoken


@pytest.mark.parametrize("ref, spoken", [
    ("country:France", "France"),
    ("country:Germany", "Germany"),
    ("continent:Africa", "Africa"),
    ("river:Nile", "the Nile river"),
    ("river:Amazon", "the Amazon river"),
    ("ocean:Atlantic Ocean", "the Atlantic Ocean"),
    ("sea:Caribbean Sea", "the Caribbean Sea"),
    ("sea:Hudson Bay", "Hudson Bay"),        # class "bay": no article
    ("lake:Lake Victoria", "Lake Victoria"),
])
def test_area_name_uses_the_pattern_for_its_kind(world, strings, ref, spoken):
    assert strings.area_name(world.resolve(ref)) == spoken


def test_area_name_of_nothing_is_the_sea(strings):
    assert strings.area_name(None) == "the sea"
    assert Strings({}).area_name(None) == "the sea"


def test_area_name_override_is_case_insensitive(world):
    s = Strings({"names": {"COUNTRY:france": "La France"}})
    assert s.area_name(world.find("country:France")) == "La France"


def test_area_name_falls_back_to_the_plain_name(world):
    s = Strings({})
    assert s.area_name(world.find("river:Nile")) == "Nile"
    assert s.area_name(world.find("country:France")) == "France"


def test_area_name_prefers_the_class_pattern_over_the_kind_pattern(world):
    bay = world.find("sea:Bay of Biscay")
    s = Strings({"name_patterns": {"sea": "the {name}", f"sea/{bay.cls}": "{name}!"}})
    assert s.area_name(bay) == "Bay of Biscay!"
    assert s.area_name(world.find("sea:Caribbean Sea")) == "the Caribbean Sea"


def test_every_names_override_points_at_a_real_area(world, raw):
    for ref in raw["names"]:
        if not ref.startswith("_"):
            assert world.find(ref) is not None, ref


def test_every_area_has_a_speakable_name(world, strings):
    for ref in world.all_ids():
        name = strings.area_name(world.find(ref))
        assert name.strip() and "{" not in name, ref


# ---- composing spoken feedback (silent speaker) ---------------------------------------------------
def test_wrong_click_sentence_is_composed_and_recorded(world, strings):
    speaker = Speaker(enabled=False)
    name = strings.area_name(world.find("country:United States of America"))
    line = strings.speech("wrong_pattern", phrase=strings.speech("wrong"),
                          that_is=strings.speech("that_is", name=name))
    speaker.say(line)
    assert speaker.history == [line]
    assert line.endswith("That is the United States.")
    assert speaker.busy is False


def test_disabled_speaker_records_everything_but_blank_text():
    speaker = Speaker(enabled=False)
    assert speaker.wait_ready(0.1)
    speaker.say("Find France on the map.")
    speaker.say("   ")
    speaker.say(None)
    speaker.say("  Good job!  ", interrupt=False)
    assert speaker.history == ["Find France on the map.", "Good job!"]
    assert speaker.available is False and speaker.busy is False
    speaker.stop()
    speaker.shutdown()


# ---- pre-recorded voice clips -------------------------------------------------------------------
def test_voice_lines_cover_everything_the_game_says(world, strings):
    from geoquiz.tasks import load_tasks
    from geoquiz.voice_lines import all_lines, clip_name, round_end_text

    tasks, _ = load_tasks(world)
    lines = all_lines(world, strings, tasks)
    assert len(lines) == len(set(lines))
    for task in tasks:
        assert task.prompt in lines
    for key in ("praise", "close", "wrong", "hint", "after_hint"):
        for phrase in strings.data["speech"][key]:
            assert phrase in lines
    for ref in ("country:Germany", "sea:Caribbean Sea", "ocean:Pacific Ocean"):
        assert strings.speech("that_is", name=strings.area_name(world.find(ref))) in lines
    assert strings.speech("that_is", name=strings.area_name(None)) in lines
    for stars in range(11):
        assert round_end_text(strings, stars, 10) in lines
    # File names are stable, distinct, and ignore stray whitespace.
    assert clip_name("Good job!") == clip_name("  Good   job! ")
    assert len({clip_name(text) for text in lines}) == len(lines)


@pytest.mark.parametrize("language", ["en", "pl"])
def test_every_sentence_has_a_recorded_clip(world, language):
    """Fails after editing a spoken text without running tools/generate_voice.py."""
    from geoquiz.tasks import load_tasks
    from geoquiz.voice_lines import all_lines, clip_name, voice_dir

    strings = Strings.load(language=language)
    tasks, _ = load_tasks(world)
    folder = voice_dir(strings.language)
    missing = [text for text in all_lines(world, strings, tasks) if not (folder / clip_name(text)).exists()]
    assert not missing, f"{len(missing)} sentences have no clip, e.g. {missing[:3]}"


def test_speaker_accepts_a_list_of_sentences():
    speaker = Speaker(enabled=False)
    speaker.say(["Not quite, try again.", "That is Germany."])
    assert speaker.history == ["Not quite, try again. That is Germany."]


# ---- Polish ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def polish():
    return Strings.load(language="pl", rng=random.Random(3))


def test_both_languages_are_available():
    from geoquiz.strings import available_languages

    assert available_languages()[:2] == ["en", "pl"]


def test_polish_file_has_the_same_keys_as_the_english_one(strings, polish):
    assert polish.language == "pl"
    for section in ("ui", "speech"):
        english = {k for k in strings.data[section] if not k.startswith("_")}
        translated = {k for k in polish.data[section] if not k.startswith("_")}
        missing = english - translated - {"round_end_one"}  # Polish uses round_end_exact instead
        assert not missing, f"{section}: not translated: {sorted(missing)}"
    for key in ("praise", "close", "wrong", "hint", "after_hint"):
        assert len(polish.data["speech"][key]) == len(strings.data["speech"][key])


def test_every_task_has_a_polish_prompt(world, polish):
    from geoquiz.tasks import load_tasks

    tasks, _ = load_tasks(world)
    for task in tasks:
        prompt = polish.prompt(task)
        assert prompt != task.prompt, f"{task.id} has no Polish prompt"
        assert prompt.endswith((".", "?", "!"))
    ids = {t.id for t in tasks}
    stale = [k for k in polish.data["prompts"] if not k.startswith("_") and k not in ids]
    assert not stale, f"Polish prompts for tasks that no longer exist: {stale}"


def test_english_strings_use_the_prompt_from_the_task_file(world, strings):
    from geoquiz.tasks import load_tasks

    tasks, _ = load_tasks(world)
    assert strings.prompt(tasks[0]) == tasks[0].prompt


def test_polish_names_point_at_real_areas_and_are_spoken(world, polish):
    for ref in polish.data["names"]:
        if not ref.startswith("_"):
            assert world.find(ref) is not None, f"unknown area id in strings.pl.json: {ref}"
    assert polish.area_name(world.find("country:Germany")) == "Niemcy"
    assert polish.area_name(world.find("sea:Baltic Sea")) == "Morze Bałtyckie"
    assert polish.area_name(world.find("ocean:Pacific Ocean")) == "Ocean Spokojny"
    assert polish.area_name(world.find("country:Albania")) == "Albania"   # same word in both
    assert polish.area_name(None) == "morze"
    assert polish.speech("that_is", name=polish.area_name(world.find("country:Poland"))) == "To Polska."
    # Every sea and ocean has a Polish name (no English "Sea"/"Gulf" left over).
    for area in list(world.seas) + list(world.oceans):
        assert area.id.lower() in {k.lower() for k in polish.data["names"]}, area.id


def test_polish_end_of_round_sentences_use_the_right_word_form(polish):
    from geoquiz.voice_lines import round_end_text

    assert "jedną gwiazdkę" in round_end_text(polish, 1, 10)
    assert "trzy gwiazdki" in round_end_text(polish, 3, 10)
    assert "pięć gwiazdek" in round_end_text(polish, 5, 10)
    assert "wszystkie dziesięć gwiazdek" in round_end_text(polish, 10, 10)
    assert round_end_text(polish, 3, 4) == "Świetna gra! Masz 3 z 4 gwiazdek."   # unusual round length
