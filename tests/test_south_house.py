from datetime import date, datetime

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.south_house import ARCHIVE_URL, SouthHouseSource
from free_food_dartmouth.utils import EASTERN

NEWSLETTER_URL = "https://newsletter.example.edu/south-week-3"


@responses.activate
def test_south_house_follows_relevant_weekly_newsletter() -> None:
    responses.get(
        ARCHIVE_URL,
        body=fixture_text("south_house_archive.html"),
        content_type="text/html",
    )
    responses.get(
        NEWSLETTER_URL,
        body=fixture_text("south_house_newsletter.html"),
        content_type="text/html",
    )

    scan = SouthHouseSource(HttpClient(attempts=1)).scan(
        date(2026, 9, 29),
        date(2026, 10, 20),
    )

    assert scan.complete
    assert len(scan.events) == 2
    dinner = next(event for event in scan.events if event.title == "South House Community Dinner")
    assert dinner.start == datetime(2026, 10, 1, 18, 0, tzinfo=EASTERN)
    assert dinner.end == datetime(2026, 10, 1, 19, 30, tzinfo=EASTERN)
    assert dinner.location == "The Onion"
    assert "explicit food-service wording" in match_event(dinner)

    council = next(event for event in scan.events if event.title == "House Council")
    assert match_event(council) == ()


@responses.activate
def test_south_house_ignores_old_newsletter_editions() -> None:
    responses.get(
        ARCHIVE_URL,
        body=fixture_text("south_house_archive.html"),
        content_type="text/html",
    )
    responses.get(
        NEWSLETTER_URL,
        body=fixture_text("south_house_newsletter.html"),
        content_type="text/html",
    )

    scan = SouthHouseSource(HttpClient(attempts=1)).scan(
        date(2026, 10, 12),
        date(2026, 11, 2),
    )

    assert scan.complete
    assert scan.events == ()
