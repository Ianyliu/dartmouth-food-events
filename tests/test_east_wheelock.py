from datetime import date, datetime, timedelta
from urllib.parse import quote

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.east_wheelock import CALENDAR_ID, EastWheelockSource
from free_food_dartmouth.utils import EASTERN

ICS_URL = (
    f"https://calendar.google.com/calendar/ical/{quote(CALENDAR_ID, safe='')}/public/basic.ics"
)


def _scan_fixture(start: date, end: date):
    responses.get(
        ICS_URL,
        body=fixture_text("east_wheelock_google.ics"),
        content_type="text/calendar",
    )
    return EastWheelockSource(HttpClient(attempts=1)).scan(start, end)


@responses.activate
def test_east_wheelock_expands_recurrences_with_exceptions_and_dst() -> None:
    scan = _scan_fixture(date(2026, 10, 26), date(2026, 11, 14))

    assert scan.complete
    assert len(scan.events) == 7
    assert len({event.source_keys for event in scan.events}) == 7

    tea = next(event for event in scan.events if event.title == "EW: Weekly Tea")
    assert tea.start == datetime(2026, 10, 26, 17, 0, tzinfo=EASTERN)
    assert tea.end == datetime(2026, 10, 26, 18, 30, tzinfo=EASTERN)
    assert tea.start.utcoffset() == timedelta(hours=-4)
    assert tea.source_keys == ("east-wheelock:weekly-tea@google.com:2026-10-26T17:00:00-04:00",)

    moved = next(event for event in scan.events if event.title == "EW: Weekly Tea (moved)")
    assert moved.start == datetime(2026, 11, 9, 18, 0, tzinfo=EASTERN)
    assert moved.end == datetime(2026, 11, 9, 19, 30, tzinfo=EASTERN)
    assert moved.start.utcoffset() == timedelta(hours=-5)
    # The moved occurrence keeps the key of the occurrence it replaces,
    # so a later move does not create a second event.
    assert moved.source_keys == ("east-wheelock:weekly-tea@google.com:2026-11-09T17:00:00-05:00",)

    assert not any(event.start_date == date(2026, 11, 2) for event in scan.events)
    assert not any(event.start_date == date(2026, 11, 16) for event in scan.events)


@responses.activate
def test_east_wheelock_excludes_cancellations_and_keeps_event_urls() -> None:
    scan = _scan_fixture(date(2026, 10, 26), date(2026, 11, 14))

    assert not any("Cancelled" in event.title for event in scan.events)
    assert not any(event.title == "EW: Cancelled Talk" for event in scan.events)

    high_tea = next(event for event in scan.events if "High Tea" in event.title)
    assert high_tea.start == datetime(2026, 10, 27, 17, 0, tzinfo=EASTERN)
    assert high_tea.urls == ("https://example.org/ew-high-tea",)
    for event in scan.events:
        assert not any("calendar.google.com" in url for url in event.urls)
        assert not any("sites.dartmouth.edu" in url for url in event.urls)


@responses.activate
def test_east_wheelock_does_not_assume_cooking_offers_food() -> None:
    scan = _scan_fixture(date(2026, 10, 26), date(2026, 11, 14))

    plain_cooking = next(
        event
        for event in scan.events
        if event.title == "EW: Cooking" and event.start_date == date(2026, 11, 3)
    )
    assert match_event(plain_cooking) == ()

    dinner_cooking = next(
        event
        for event in scan.events
        if event.title == "EW: Cooking" and event.start_date == date(2026, 11, 10)
    )
    assert "explicit food-service wording" in match_event(dinner_cooking)


@responses.activate
def test_east_wheelock_tolerates_missing_location_and_all_day_events() -> None:
    scan = _scan_fixture(date(2026, 10, 26), date(2026, 11, 14))

    study = next(event for event in scan.events if event.title == "EW: Study Night")
    assert study.location == ""

    rest = next(event for event in scan.events if event.title == "EW: Day of Rest")
    assert rest.start == date(2026, 11, 1)
    assert rest.end == date(2026, 11, 2)
    assert rest.all_day


@responses.activate
def test_east_wheelock_rdate_only_series_includes_dtstart() -> None:
    responses.get(
        ICS_URL,
        body=(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
            "BEGIN:VEVENT\r\nUID:rdate-only@google.com\r\n"
            "DTSTART;TZID=America/New_York:20261028T170000\r\n"
            "DTEND;TZID=America/New_York:20261028T180000\r\n"
            "RDATE;TZID=America/New_York:20261104T170000\r\n"
            "SUMMARY:EW: Pop-up Tea\r\nLOCATION:Brace Commons\r\n"
            "STATUS:CONFIRMED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ),
        content_type="text/calendar",
    )

    scan = EastWheelockSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 14))

    assert scan.complete
    assert [event.start_date for event in scan.events] == [
        date(2026, 10, 28),
        date(2026, 11, 4),
    ]
    assert len({event.source_keys for event in scan.events}) == 2


@responses.activate
def test_east_wheelock_orphan_override_is_its_own_event() -> None:
    responses.get(
        ICS_URL,
        body=(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
            "BEGIN:VEVENT\r\nUID:orphan@google.com\r\n"
            "RECURRENCE-ID;TZID=America/New_York:20261106T170000\r\n"
            "DTSTART;TZID=America/New_York:20261106T180000\r\n"
            "DTEND;TZID=America/New_York:20261106T190000\r\n"
            "SUMMARY:EW: Rescheduled Tea\r\nLOCATION:Brace Commons\r\n"
            "STATUS:CONFIRMED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ),
        content_type="text/calendar",
    )

    scan = EastWheelockSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 14))

    assert scan.complete
    assert len(scan.events) == 1
    assert scan.events[0].start == datetime(2026, 11, 6, 18, 0, tzinfo=EASTERN)
    assert scan.events[0].source_keys == (
        "east-wheelock:orphan@google.com:2026-11-06T17:00:00-05:00",
    )


@responses.activate
def test_east_wheelock_multiple_exdate_rdate_lines_honored_across_dst() -> None:
    """Separate EXDATE/RDATE properties must all apply (icalendar 7
    returns a list of vDDDLists for them), across the Nov 1 DST change.
    The Nov 2 exclusion is TZID-based and the Nov 9 exclusion is UTC;
    both must drop their occurrences, and both RDATE additions must
    appear, so excluded occurrences can never reach publication."""
    responses.get(
        ICS_URL,
        body=(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
            "BEGIN:VEVENT\r\nUID:series@google.com\r\n"
            "DTSTART;TZID=America/New_York:20261026T170000\r\n"
            "DTEND;TZID=America/New_York:20261026T180000\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=5;BYDAY=MO\r\n"
            "EXDATE;TZID=America/New_York:20261102T170000\r\n"
            "EXDATE:20261109T220000Z\r\n"
            "RDATE;TZID=America/New_York:20261104T170000\r\n"
            "RDATE:20261111T220000Z\r\n"
            "SUMMARY:Weekly Tea\r\nLOCATION:Brace Commons\r\n"
            "STATUS:CONFIRMED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ),
        content_type="text/calendar",
    )

    scan = EastWheelockSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 17))

    assert scan.complete
    assert [event.start.isoformat() for event in scan.events] == [
        "2026-10-26T17:00:00-04:00",
        "2026-11-04T17:00:00-05:00",
        "2026-11-11T17:00:00-05:00",
        "2026-11-16T17:00:00-05:00",
    ]
    assert {event.source_keys[0] for event in scan.events} == {
        "east-wheelock:series@google.com:2026-10-26T17:00:00-04:00",
        "east-wheelock:series@google.com:2026-11-04T17:00:00-05:00",
        "east-wheelock:series@google.com:2026-11-11T17:00:00-05:00",
        "east-wheelock:series@google.com:2026-11-16T17:00:00-05:00",
    }


@responses.activate
def test_east_wheelock_empty_window_is_complete_not_a_failure() -> None:
    scan = _scan_fixture(date(2026, 9, 1), date(2026, 9, 30))

    assert scan.complete
    assert scan.events == ()


@responses.activate
def test_east_wheelock_malformed_feed_raises_instead_of_empty() -> None:
    responses.get(ICS_URL, body="<html>not a calendar</html>", content_type="text/html")

    try:
        EastWheelockSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 14))
    except ValueError as exc:
        assert "iCalendar" in str(exc)
    else:
        raise AssertionError("expected malformed feed to raise")


@responses.activate
def test_east_wheelock_broken_component_is_incomplete_but_keeps_good_events() -> None:
    broken = fixture_text("east_wheelock_google.ics").replace(
        "UID:single-utc@google.com", "SUMMARY:EW: Broken Event\nUID:"
    )
    responses.get(ICS_URL, body=broken, content_type="text/calendar")

    scan = EastWheelockSource(HttpClient(attempts=1)).scan(date(2026, 10, 26), date(2026, 11, 14))

    assert not scan.complete
    assert scan.errors and "UID" in scan.errors[0]
    assert any(event.title == "EW: Weekly Tea" for event in scan.events)
