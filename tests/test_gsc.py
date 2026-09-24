from datetime import date, datetime

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.gsc import EVENTS_URL, GscSource
from free_food_dartmouth.utils import EASTERN


@responses.activate
def test_gsc_scan_reads_squarespace_event_list_and_food_wording() -> None:
    responses.get(EVENTS_URL, body=fixture_text("gsc_events.html"), content_type="text/html")

    scan = GscSource(HttpClient(attempts=1)).scan(date(2026, 9, 23), date(2026, 10, 14))

    assert scan.complete
    assert len(scan.events) == 3

    spark = next(event for event in scan.events if event.title == "SPARK Game Night")
    assert spark.start == datetime(2026, 9, 29, 17, 0, tzinfo=EASTERN)
    assert spark.end == datetime(2026, 9, 29, 19, 0, tzinfo=EASTERN)
    assert spark.location == "Guarini Commons"
    assert spark.source_keys == ("gsc:spark-game-night",)
    assert "https://example.org/spark-rsvp" in spark.urls
    assert match_event(spark)

    book_club = next(event for event in scan.events if event.title == "Dartmouth Book Club")
    assert match_event(book_club) == ()


def test_gsc_multiday_event_uses_first_date_and_next_day_end() -> None:
    soup = fixture_text("gsc_events.html")
    with responses.RequestsMock() as mocked:
        mocked.get(EVENTS_URL, body=soup, content_type="text/html")
        scan = GscSource(HttpClient(attempts=1)).scan(date(2026, 10, 9), date(2026, 10, 11))

    assert scan.complete
    assert len(scan.events) == 1
    event = scan.events[0]
    assert event.title == "First Year Graduate Student Cabin Trip (GSC)"
    assert event.start == datetime(2026, 10, 9, 16, 30, tzinfo=EASTERN)
    assert event.end == datetime(2026, 10, 10, 12, 0, tzinfo=EASTERN)
