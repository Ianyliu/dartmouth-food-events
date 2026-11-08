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
def test_south_house_probes_ahead_of_stale_archive() -> None:
    # Regression test for Nov 2026: the archive page still listed
    # Week 6 (Oct. 19) as LATEST while Week 7 existed at the
    # sequential Mailchimp URL, so the scan found zero South events
    # and previously managed South events aged out of the feed.
    # Probing a few weeks ahead of the latest archive issue must
    # discover Week 7 and stop at the Week 8 404.
    archive = (
        "<!doctype html><html><body><h2>Fall 2026</h2>"
        '<p><a href="https://mailchi.mp/dartmouth/south-house-weekly-26f-week-6">'
        "26F - Week 6 (Oct. 19, 2026)</a></p></body></html>"
    )
    responses.get(ARCHIVE_URL, body=archive, content_type="text/html")
    responses.get(
        "https://mailchi.mp/dartmouth/south-house-weekly-26f-week-6",
        body=fixture_text("south_house_mailchimp.html"),
        content_type="text/html",
    )
    responses.get(
        "https://mailchi.mp/dartmouth/south-house-weekly-26f-week-7",
        body=fixture_text("south_house_mailchimp_week7.html"),
        content_type="text/html",
    )
    responses.get(
        "https://mailchi.mp/dartmouth/south-house-weekly-26f-week-8",
        status=404,
        content_type="text/html",
    )

    scan = SouthHouseSource(HttpClient(attempts=1)).scan(
        date(2026, 11, 1),
        date(2026, 11, 22),
    )

    assert scan.complete
    by_title = {event.title: event for event in scan.events}
    assert "Being a Public Advocate for the Earth: An Evening with Chuck Sams" in by_title
    assert by_title[
        "Being a Public Advocate for the Earth: An Evening with Chuck Sams"
    ].start == datetime(2026, 11, 2, 17, 30, tzinfo=EASTERN)
    assert "Fuel Up for Finals" in by_title
    assert by_title["Fuel Up for Finals"].start == datetime(2026, 11, 3, 18, 30, tzinfo=EASTERN)
    assert by_title["Fuel Up for Finals"].location == "Fayerweather Great Hall"
    assert "Loy Krathong" in by_title
    assert by_title["Loy Krathong"].start == datetime(2026, 11, 6, 18, 0, tzinfo=EASTERN)
    assert "International Student Appreciation" in by_title
    assert by_title["International Student Appreciation"].start == datetime(
        2026, 11, 17, 9, 30, tzinfo=EASTERN
    )
    assert by_title["International Student Appreciation"].location == "The Cube"


def test_south_house_skips_mixed_case_upcoming_events_header() -> None:
    # Regression test for Week 8 (Nov 2026): the newsletter renders
    # its "Upcoming Events" section header in title case, so the
    # all-caps section-header check missed it and the parser published
    # a bogus "Upcoming Events" event instead of the Finals Stress
    # Relief: Yoga & Brunch event that follows it. The newsletter
    # gives no "Where:" line for that event, so the venue (Mighty
    # Yoga Studio) comes through in the description, and the 9:30 AM
    # start with no end time takes the parser's one-hour default.
    events = SouthHouseSource._events(
        fixture_text("south_house_mailchimp_week8.html"),
        date(2026, 11, 2),
        "https://mailchi.mp/dartmouth/south-house-weekly-26f-week-8",
        date(2026, 11, 8),
        date(2026, 11, 29),
    )
    by_title = {event.title: event for event in events}
    assert set(by_title) == {
        "Finals Stress Relief: Yoga & Brunch",
        "International Student Appreciation",
    }
    yoga = by_title["Finals Stress Relief: Yoga & Brunch"]
    assert yoga.start == datetime(2026, 11, 19, 9, 30, tzinfo=EASTERN)
    assert yoga.end == datetime(2026, 11, 19, 10, 30, tzinfo=EASTERN)
    assert yoga.location == ""
    assert "Mighty Yoga Studio" in yoga.description
    assert "food or meal keyword in title" in match_event(yoga)


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
