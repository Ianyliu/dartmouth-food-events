from datetime import date
from urllib.parse import quote

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.sources.west_house import CALENDAR_ID, WestHouseSource

ICS_URL = (
    f"https://calendar.google.com/calendar/ical/{quote(CALENDAR_ID, safe='')}/public/basic.ics"
)


@responses.activate
def test_west_house_stale_feed_is_a_complete_empty_window() -> None:
    responses.get(
        ICS_URL,
        body=fixture_text("west_house_google.ics"),
        content_type="text/calendar",
    )

    scan = WestHouseSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 14))

    assert scan.complete
    assert scan.events == ()


@responses.activate
def test_west_house_emits_current_events_when_present() -> None:
    responses.get(
        ICS_URL,
        body=(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
            "BEGIN:VEVENT\r\nUID:tea-20261106@google.com\r\n"
            "DTSTART;TZID=America/New_York:20261106T160000\r\n"
            "DTEND;TZID=America/New_York:20261106T170000\r\n"
            "SUMMARY:West House Friday Tea\r\nLOCATION:House Professor's Residence\r\n"
            "DESCRIPTION:Tea and cookies will be served.\r\nSTATUS:CONFIRMED\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        ),
        content_type="text/calendar",
    )

    scan = WestHouseSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 14))

    assert scan.complete
    assert len(scan.events) == 1
    assert scan.events[0].title == "West House Friday Tea"
    assert scan.events[0].source_keys == ("west-house:tea-20261106@google.com",)


@responses.activate
def test_west_house_malformed_feed_raises_instead_of_empty() -> None:
    responses.get(ICS_URL, body="not a calendar", content_type="text/plain")

    try:
        WestHouseSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 14))
    except ValueError as exc:
        assert "iCalendar" in str(exc)
    else:
        raise AssertionError("expected malformed feed to raise")
