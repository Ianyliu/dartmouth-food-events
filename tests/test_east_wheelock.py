from datetime import date, datetime
from urllib.parse import quote

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.east_wheelock import HOME_URL, EastWheelockSource
from free_food_dartmouth.utils import EASTERN

CALENDAR_ID = "east.wheelock.house@group.calendar.google.com"
ICS_URL = (
    "https://calendar.google.com/calendar/ical/"
    f"{quote(CALENDAR_ID, safe='')}/public/basic.ics"
)


@responses.activate
def test_east_wheelock_reads_embedded_public_google_calendar() -> None:
    responses.get(
        HOME_URL,
        body=fixture_text("east_wheelock_home.html"),
        content_type="text/html",
    )
    responses.get(
        ICS_URL,
        body=fixture_text("east_wheelock.ics"),
        content_type="text/calendar",
    )

    scan = EastWheelockSource(HttpClient(attempts=1)).scan(
        date(2026, 9, 29), date(2026, 10, 20)
    )

    assert scan.complete
    assert len(scan.events) == 2
    dinner = next(event for event in scan.events if event.title.endswith("Community Dinner"))
    assert dinner.start == datetime(2026, 10, 3, 18, 0, tzinfo=EASTERN)
    assert dinner.end == datetime(2026, 10, 3, 19, 30, tzinfo=EASTERN)
    assert dinner.location == "Brace Commons"
    assert dinner.source_keys == ("east-wheelock:ew-community-dinner-20261003",)
    assert "explicit food-service wording" in match_event(dinner)

    study = next(event for event in scan.events if event.title == "Study Night")
    assert match_event(study) == ()


def test_east_wheelock_requires_a_public_calendar_embed() -> None:
    try:
        EastWheelockSource._calendar_id("<html><body>No calendar</body></html>")
    except ValueError as exc:
        assert "Google Calendar embed" in str(exc)
    else:
        raise AssertionError("expected missing calendar embed to fail")
