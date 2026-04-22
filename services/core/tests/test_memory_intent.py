"""memory/calendar intent extraction helpers."""

from memoryagent.memory_intent import extract_memory_save_text
from memoryagent.calendar_intent import (
    parse_calendar_create_intent,
    parse_calendar_lookup_intent,
    title_keywords,
)


def test_extract_remember_that() -> None:
    assert extract_memory_save_text("Remember that my code is 42.") == "my code is 42."
    assert extract_memory_save_text("please remember that   cats are great") == "cats are great"


def test_extract_note_and_aliases() -> None:
    assert extract_memory_save_text("note: parking level B2") == "parking level B2"
    assert extract_memory_save_text("Save to memory: dentist is Dr. Lee") == "dentist is Dr. Lee"
    assert extract_memory_save_text("memorize: alpha-beta-99") == "alpha-beta-99"


def test_extract_none_when_not_save_intent() -> None:
    assert extract_memory_save_text("What is my favorite color?") is None
    assert extract_memory_save_text("Remember the Alamo") is None  # not "remember that"


def test_extract_empty_body() -> None:
    assert extract_memory_save_text("Remember that") is None
    assert extract_memory_save_text("remember:  ") is None


def test_parse_calendar_create_structured() -> None:
    i = parse_calendar_create_intent(
        "create calendar event: title=Dentist checkup; starts_at=2026-07-01T14:00:00Z; location=Smile Clinic"
    )
    assert i is not None
    assert i.title == "Dentist checkup"
    assert i.starts_at == "2026-07-01T14:00:00Z"
    assert i.location == "Smile Clinic"


def test_parse_calendar_create_requires_title_and_starts_at() -> None:
    assert parse_calendar_create_intent("create calendar event: title=Only title") is None
    assert parse_calendar_create_intent("create calendar event: starts_at=2026-01-01T00:00:00Z") is None


def test_parse_calendar_create_natural() -> None:
    i = parse_calendar_create_intent(
        "Schedule dentist checkup at 2026-07-01T14:00:00Z to 2026-07-01T15:00:00Z in Smile Clinic"
    )
    assert i is not None
    assert i.title == "dentist checkup"
    assert i.starts_at == "2026-07-01T14:00:00Z"
    assert i.ends_at == "2026-07-01T15:00:00Z"
    assert i.location == "Smile Clinic"


def test_title_keywords() -> None:
    kws = title_keywords("The Dentist Follow-up at Smile Clinic")
    assert "dentist" in kws
    assert "smile" in kws


def test_parse_calendar_lookup_intent_with_month() -> None:
    i = parse_calendar_lookup_intent("let me get the date and time of appointment at Takashi Dental in June")
    assert i is not None
    assert "takashi" in i.keywords
    assert "dental" in i.keywords
    assert i.month_start_iso is not None
    assert i.month_end_iso is not None


def test_parse_calendar_lookup_intent_none_for_unrelated_text() -> None:
    assert parse_calendar_lookup_intent("tell me a joke") is None
