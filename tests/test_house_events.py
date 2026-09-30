from datetime import date, datetime

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.house_events import (
    NORTH_PARK,
    SCHOOL_HOUSE,
    HouseEventListSource,
)
from free_food_dartmouth.utils import EASTERN


@responses.activate
def test_house_event_list_parses_squarespace_events() -> None:
    responses.get(
        NORTH_PARK.events_url,
        body=fixture_text("house_event_list.html"),
        content_type="text/html",
    )

    scan = HouseEventListSource(NORTH_PARK, HttpClient(attempts=1)).scan(
        date(2026, 9, 29),
        date(2026, 10, 20),
    )

    assert scan.complete
    assert len(scan.events) == 1
    event = scan.events[0]
    assert event.title == "Community Dinner"
    assert event.start == datetime(2026, 10, 2, 18, 0, tzinfo=EASTERN)
    assert event.end == datetime(2026, 10, 2, 19, 30, tzinfo=EASTERN)
    assert event.location == "Occom Commons"
    assert event.source_keys == ("north-park-house:community-dinner",)
    assert "https://example.org/rsvp" in event.urls
    assert "explicit food-service wording" in match_event(event)


@responses.activate
def test_school_house_uses_its_own_source_identity() -> None:
    school_fixture = fixture_text("house_event_list.html").replace(
        "/house-events/community-dinner",
        "/new-events/community-dinner",
    )
    responses.get(SCHOOL_HOUSE.events_url, body=school_fixture, content_type="text/html")

    scan = HouseEventListSource(SCHOOL_HOUSE, HttpClient(attempts=1)).scan(
        date(2026, 9, 29),
        date(2026, 10, 20),
    )

    event = scan.events[0]
    assert event.sponsor == "School House"
    assert event.sources == ("School House",)
    assert event.source_keys == ("school-house:community-dinner",)


@responses.activate
def test_house_event_list_skips_stale_multiday_entries_cleanly() -> None:
    responses.get(
        NORTH_PARK.events_url,
        body=fixture_text("house_event_list.html"),
        content_type="text/html",
    )

    scan = HouseEventListSource(NORTH_PARK, HttpClient(attempts=1)).scan(
        date(2026, 9, 29),
        date(2026, 10, 20),
    )

    assert scan.complete
    assert len(scan.events) == 1
    assert scan.events[0].title == "Community Dinner"
