"""Starter prompt templates: only renderable ones reach the home screen."""

from src.agent_runtime.suggestions import FALLBACK, clean

AREA = {"label": "area", "options": ["Austin, TX", " ", 7]}


def test_keeps_defined_blanks_and_drops_bad_options():
    assert clean([{"text": "Find 10 dentists in {area}", "slots": {"area": AREA}}]) == [
        {"text": "Find 10 dentists in {area}", "slots": {"area": {"label": "area", "options": ["Austin, TX"]}}}
    ]


def test_drops_templates_with_undefined_repeated_or_too_many_blanks():
    assert clean([
        {"text": "Find {business} in {area}", "slots": {"area": AREA}},
        {"text": "{area} or {area}", "slots": {"area": AREA}},
        {"text": "{a} {b} {c} {d}", "slots": {k: AREA for k in "abcd"}},
        {"text": "Find 10 {business type} in {area}", "slots": {"area": AREA}},
        "not a template",
        {"text": 5},
    ]) == []


def test_multi_word_blank_names_become_one_word():
    kept = clean([{"text": "Map {Contact Group}", "slots": {"contact group": {"options": ["owners"]}}}])
    assert kept == [{"text": "Map {contact_group}", "slots": {"contact_group": {"label": "contact group", "options": ["owners"]}}}]


def test_plain_prompt_without_blanks_is_kept():
    assert clean([{"text": "How many credits do I have left?"}]) == [{"text": "How many credits do I have left?", "slots": {}}]


def test_fallback_sets_are_valid():
    for mode, templates in FALLBACK.items():
        assert clean(templates) == templates, mode
