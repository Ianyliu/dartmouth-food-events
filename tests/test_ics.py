from datetime import date, datetime, timedelta

from icalendar import Calendar

from free_food_dartmouth.ics import build_calendar
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.utils import EASTERN


def test_generated_calendar_has_unique_stable_uids_and_all_day_dates() -> None:
    timed_start = datetime(2026, 7, 9, 12, tzinfo=EASTERN)
    events = [
        EventRecord(
            "Lunch",
            timed_start,
            timed_start + timedelta(hours=1),
            "Lunch is provided.",
            source_keys=("dartmouth:1",),
            uid_key="dartmouth:1",
        ),
        EventRecord(
            "Reception",
            date(2026, 7, 10),
            date(2026, 7, 11),
            "Reception",
            source_keys=("geisel:2:2026-7-10",),
            uid_key="geisel:2:2026-7-10",
            tentative=True,
        ),
    ]
    payload = build_calendar(events, datetime(2026, 7, 1, tzinfo=EASTERN)).to_ical()
    parsed = Calendar.from_ical(payload)
    components = [item for item in parsed.walk() if item.name == "VEVENT"]
    assert len({str(item["UID"]) for item in components}) == 2
    assert components[1].decoded("DTSTART") == date(2026, 7, 10)
    assert str(components[1]["STATUS"]) == "TENTATIVE"
