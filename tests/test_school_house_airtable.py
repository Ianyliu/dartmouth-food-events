from datetime import date, datetime
from pathlib import Path

import pytest
from conftest import fixture_text

from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.school_house_airtable import SchoolHouseAirtableSource
from free_food_dartmouth.utils import EASTERN


def test_school_house_airtable_imports_food_and_filters_cancellations(tmp_path: Path) -> None:
    path = tmp_path / "school-house.ics"
    path.write_text(fixture_text("school_house_airtable.ics"), encoding="utf-8")
    scan = SchoolHouseAirtableSource(path).scan(date(2026, 10, 14), date(2026, 11, 4))
    assert scan.complete
    assert len(scan.events) == 3

    grounds = next(event for event in scan.events if event.title.startswith("School Grounds"))
    assert grounds.title.endswith("every Friday")
    assert grounds.start == datetime(2026, 10, 23, 8, 30, tzinfo=EASTERN)
    assert grounds.source_keys[0].startswith("school-house-airtable:recSchoolGrounds01:")
    assert grounds.primary_url.startswith("https://airtable.com/")
    assert "food or meal keyword in title" in match_event(grounds)

    waffle = next(event for event in scan.events if "Waffle" in event.title)
    assert waffle.start == datetime(2026, 10, 15, 20, 0, tzinfo=EASTERN)
    council = next(event for event in scan.events if "Council" in event.title)
    assert council.title == "School House Council Meeting"
    assert match_event(council) == ()


def test_school_house_airtable_missing_export_is_never_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCHOOL_HOUSE_AIRTABLE_ICS", raising=False)
    with pytest.raises(RuntimeError, match="fresh Airtable export"):
        SchoolHouseAirtableSource().scan(date(2026, 10, 14), date(2026, 11, 4))


def test_school_house_airtable_rejects_invalid_export(tmp_path: Path) -> None:
    path = tmp_path / "bad.ics"
    path.write_text("<html>login required</html>", encoding="utf-8")
    with pytest.raises(ValueError, match="not an iCalendar"):
        SchoolHouseAirtableSource(path).scan(date(2026, 10, 14), date(2026, 11, 4))
