from datetime import date

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.german_studies import (
    LIST_URL,
    GermanStudiesSource,
    _extract_event,
)

OKTOBERFEST_URL = "https://german.dartmouth.edu/news/2026/10/oktoberfest-2026-october-8-430-630"
FOREST_URL = "https://german.dartmouth.edu/news/2026/10/forest-bathing"
RECAP_URL = (
    "https://german.dartmouth.edu/news/2026/10/"
    "german-studies-allen-and-west-houses-host-festive-oktoberfest-celebration-cube"
)


def _register_listing_and_details() -> None:
    responses.get(LIST_URL, body=fixture_text("german_studies_news.html"))
    responses.get(OKTOBERFEST_URL, body=fixture_text("german_oktoberfest.html"))
    responses.get(FOREST_URL, body=fixture_text("german_forest_bathing.html"))
    responses.get(RECAP_URL, body=fixture_text("german_oktoberfest_recap.html"))


@responses.activate
def test_german_studies_announcement_parses_but_recap_and_unhosted_do_not() -> None:
    _register_listing_and_details()

    scan = GermanStudiesSource(HttpClient(attempts=1)).scan(date(2026, 9, 29), date(2026, 10, 20))

    assert scan.complete
    assert len(scan.events) == 1
    event = scan.events[0]
    assert event.title == "Oktoberfest 2026! October 8, 4:30-6:30"
    assert event.start.isoformat() == "2026-10-08T16:30:00-04:00"
    assert event.end.isoformat() == "2026-10-08T18:30:00-04:00"
    assert event.location == "The Cube"
    assert event.urls == (OKTOBERFEST_URL,)
    assert event.source_keys == ("german-studies:oktoberfest-2026-october-8-430-630",)
    assert "food keyword near service context" in match_event(event)


@responses.activate
def test_german_studies_past_window_yields_no_events() -> None:
    _register_listing_and_details()

    scan = GermanStudiesSource(HttpClient(attempts=1)).scan(date(2026, 10, 23), date(2026, 11, 13))

    assert scan.complete
    assert scan.events == ()


def test_german_studies_extracts_bare_times_and_morning_context() -> None:
    assert _extract_event(
        "Oktoberfest 2026! October 8, 4:30-6:30",
        "Allen House and West House invite you to join us on Thursday, "
        "October 8th from 4:30-6:30 at The Cube. There will be food.",
        date(2026, 10, 5),
    ) == (date(2026, 10, 8), 16 * 60 + 30, 18 * 60 + 30, "The Cube")

    assert _extract_event(
        "Forest Bathing",
        "Allen House invites you to join us. October 13th, 12:15-2:00, DCAL & BEMA.",
        date(2026, 10, 6),
    ) == (date(2026, 10, 13), 12 * 60 + 15, 14 * 60, "")

    assert _extract_event(
        "Brunch",
        "Allen House invites you to brunch on October 20th, 10-11 in the morning at Brace Commons.",
        date(2026, 10, 15),
    ) == (date(2026, 10, 20), 10 * 60, 11 * 60, "Brace Commons")


def test_german_studies_date_ranges_markers_and_multiple_dates() -> None:
    # A date range without a clock time is skipped, never dated to an
    # invented evening time; with a real clock time it takes the range's
    # first day.
    assert (
        _extract_event(
            "Fall Gathering",
            "Join us October 8-10 at Allen House for a fall gathering.",
            date(2026, 10, 1),
        )
        is None
    )
    assert _extract_event(
        "Fall Gathering",
        "Join us October 8-10, 4:30-6:30 PM at Allen House.",
        date(2026, 10, 1),
    ) == (date(2026, 10, 8), 16 * 60 + 30, 18 * 60 + 30, "Allen House")

    # A marker on one endpoint applies to both; a marker on each applies
    # to its own.
    assert _extract_event(
        "Morning Coffee",
        "Join us October 30, 9-10 AM at Allen House for coffee.",
        date(2026, 10, 20),
    ) == (date(2026, 10, 30), 9 * 60, 10 * 60, "Allen House")
    assert _extract_event(
        "Lunch Talk",
        "Join us November 5, 11 AM-1 PM at Allen House.",
        date(2026, 10, 20),
    ) == (date(2026, 11, 5), 11 * 60, 13 * 60, "Allen House")
    assert _extract_event(
        "Evening Social",
        "Allen House and West House invite you to join us on Thursday, "
        "October 8th from 4:30-6:30 PM at The Cube.",
        date(2026, 10, 1),
    ) == (date(2026, 10, 8), 16 * 60 + 30, 18 * 60 + 30, "The Cube")
    assert _extract_event(
        "Midnight Snack",
        "Allen House invites you to join us October 20th, 12-1 in the morning at Brace Commons.",
        date(2026, 10, 15),
    ) == (date(2026, 10, 20), 0, 60, "Brace Commons")

    # A publication date printed before the event date does not end the
    # search when it carries no time of its own.
    assert _extract_event(
        "Morning Coffee",
        "Posted October 20, 2026. Join us October 30, 9-10 AM at Allen House for coffee.",
        date(2026, 10, 20),
    ) == (date(2026, 10, 30), 9 * 60, 10 * 60, "Allen House")

    # Several prospective timed dates are ambiguous: skip, don't guess.
    assert (
        _extract_event(
            "Two Events?",
            "Join us October 30, 9-10 AM at Allen House. Also November 5, 2-3 PM at Allen House.",
            date(2026, 10, 20),
        )
        is None
    )
    # A retrospective timed mention does not create that ambiguity.
    assert _extract_event(
        "Morning Coffee",
        "Last year October 8, 4:30-6:30 PM was wonderful. "
        "Join us October 30, 9-10 AM at Allen House.",
        date(2026, 10, 20),
    ) == (date(2026, 10, 30), 9 * 60, 10 * 60, "Allen House")


def test_german_studies_skips_undated_unhosted_and_recap_items() -> None:
    assert (
        _extract_event(
            "Social",
            "Allen House invites you to a social.",
            date(2026, 10, 5),
        )
        is None
    )
    assert (
        _extract_event(
            "Social",
            "Join us on October 20th, 5-6 at Brace Commons.",
            date(2026, 10, 15),
        )
        is None
    )
    assert (
        _extract_event(
            "Recap",
            "West House turned out on October 8th from 4:30-6:30 at The Cube. "
            "Thank you to everyone who came!",
            date(2026, 10, 9),
        )
        is None
    )


def test_german_studies_rolls_december_announcement_into_january() -> None:
    assert _extract_event(
        "Winter Social",
        "West House invites you to a social on January 10th, 5-6 at Brace Commons.",
        date(2026, 12, 15),
    ) == (date(2027, 1, 10), 17 * 60, 18 * 60, "Brace Commons")


@responses.activate
def test_german_studies_empty_listing_raises() -> None:
    responses.get(LIST_URL, body="<html><body><p>Nothing here</p></body></html>")

    try:
        GermanStudiesSource(HttpClient(attempts=1)).scan(date(2026, 10, 23), date(2026, 11, 13))
    except ValueError as exc:
        assert "no articles" in str(exc)
    else:
        raise AssertionError("expected empty listing to raise")


@responses.activate
def test_german_studies_detail_failure_is_incomplete() -> None:
    responses.get(
        LIST_URL,
        body=(
            '<html><body><div class="views-row"><h3><a href="/news/2026/10/'
            'oktoberfest-2026-october-8-430-630">Oktoberfest 2026! October 8, 4:30-6:30'
            "</a></h3><div>October 05, 2026</div></div></body></html>"
        ),
    )
    responses.get(OKTOBERFEST_URL, status=500)

    scan = GermanStudiesSource(HttpClient(attempts=1)).scan(date(2026, 9, 29), date(2026, 10, 20))

    assert not scan.complete
    assert scan.events == ()
    assert scan.errors and OKTOBERFEST_URL in scan.errors[0]
