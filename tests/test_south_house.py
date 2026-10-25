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


def test_south_house_mailchimp_where_when_blocks() -> None:
    # Regression test for the Week 6 (Oct 2026) misalignment: the old
    # parser took the previous event's "Where:" line as the title, the
    # next event's body as the description, and parsed "5:30-6:30pm"
    # as starting at 6:30pm.
    events = SouthHouseSource._events(
        fixture_text("south_house_mailchimp.html"),
        date(2026, 10, 19),
        "https://mailchi.mp/dartmouth/south-house-weekly-26f-week-6",
        date(2026, 10, 25),
        date(2026, 11, 15),
    )
    by_title = {event.title: event for event in events}
    assert set(by_title) == {
        "SxSH: Data, Power, and Inequality: A Conversation with Prof. Roopika Risam",
        "Paint by Numbers & Movie Night",
        "Doing Well by Doing Good: A Dinner and Discussion",
        "Cube-o-ween",
        "Being a Public Advocate for the Earth: An Evening with Chuck Sams",
    }
    risam = by_title["SxSH: Data, Power, and Inequality: A Conversation with Prof. Roopika Risam"]
    assert risam.start == datetime(2026, 10, 26, 17, 30, tzinfo=EASTERN)
    assert risam.end == datetime(2026, 10, 26, 18, 30, tzinfo=EASTERN)
    assert risam.location == "5 Sanborn Road (South House Professor Home)"
    assert "Roopika Risam" in risam.description
    paint = by_title["Paint by Numbers & Movie Night"]
    assert paint.start == datetime(2026, 10, 27, 20, 0, tzinfo=EASTERN)
    assert paint.end == datetime(2026, 10, 27, 22, 30, tzinfo=EASTERN)
    assert paint.location == "Fayerweather Great Hall"
    doing_well = by_title["Doing Well by Doing Good: A Dinner and Discussion"]
    assert doing_well.start == datetime(2026, 10, 28, 17, 30, tzinfo=EASTERN)
    assert doing_well.end == datetime(2026, 10, 28, 19, 30, tzinfo=EASTERN)
    cube = by_title["Cube-o-ween"]
    assert cube.start == datetime(2026, 10, 31, 22, 0, tzinfo=EASTERN)
    assert cube.end == datetime(2026, 11, 1, 0, 0, tzinfo=EASTERN)
    assert cube.location == "The Cube"
    chuck = by_title["Being a Public Advocate for the Earth: An Evening with Chuck Sams"]
    assert chuck.start == datetime(2026, 11, 2, 17, 30, tzinfo=EASTERN)
    assert chuck.location == "7 School Street (School House Professor home)"


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
