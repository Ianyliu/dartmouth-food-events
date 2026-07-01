from datetime import date, datetime

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.sources.dartmouth import DETAIL_URL as DARTMOUTH_DETAIL
from free_food_dartmouth.sources.dartmouth import ICS_URL, SEARCH_URL, DartmouthSource
from free_food_dartmouth.sources.dartmouth_groups import DETAIL_URL as GROUPS_DETAIL
from free_food_dartmouth.sources.dartmouth_groups import LIST_URL, DartmouthGroupsSource
from free_food_dartmouth.sources.geisel import DETAIL_URL as GEISEL_DETAIL
from free_food_dartmouth.sources.geisel import INDEX_URL, GeiselSource


@responses.activate
def test_dartmouth_scan_uses_search_json_ld_and_event_ics() -> None:
    responses.get(
        SEARCH_URL, body=fixture_text("dartmouth_search.json"), content_type="application/json"
    )
    responses.get(
        f"{DARTMOUTH_DETAIL}?event=81981",
        body=fixture_text("dartmouth_detail.html"),
        content_type="text/html",
    )
    responses.get(
        ICS_URL.format(event_id="81981"),
        body=fixture_text("dartmouth_event.ics"),
        content_type="text/calendar",
    )

    scan = DartmouthSource(HttpClient(attempts=1), workers=1).scan(
        date(2026, 7, 1), date(2026, 7, 15)
    )

    assert scan.complete
    assert len(scan.events) == 1
    event = scan.events[0]
    assert event.title == "Pizza Retreat"
    assert event.start == datetime(2026, 7, 9, 13, 0, tzinfo=event.start.tzinfo)
    assert event.location == "Dartmouth Organic Farm"
    assert event.sponsor == "Student Wellness Center"
    assert event.categories == ("Free Food", "Spiritual & Worship")
    assert "https://example.org/rsvp" in event.urls


@responses.activate
def test_dartmouth_scan_falls_back_when_event_ics_is_broken() -> None:
    responses.get(
        SEARCH_URL,
        body=fixture_text("dartmouth_search.json"),
        content_type="application/json",
    )
    responses.get(
        f"{DARTMOUTH_DETAIL}?event=81981",
        body=fixture_text("dartmouth_detail.html"),
        content_type="text/html",
    )
    responses.get(ICS_URL.format(event_id="81981"), status=500)

    scan = DartmouthSource(HttpClient(attempts=1), workers=1).scan(
        date(2026, 7, 1), date(2026, 7, 15)
    )

    event = scan.events[0]
    assert event.start == datetime(2026, 7, 9, 13, 0, tzinfo=event.start.tzinfo)
    assert event.end == datetime(2026, 7, 9, 18, 0, tzinfo=event.end.tzinfo)


@responses.activate
def test_geisel_scan_deduplicates_references_and_reads_detail_rows() -> None:
    responses.get(INDEX_URL, body=fixture_text("geisel_week.html"), content_type="text/html")
    responses.get(
        f"{GEISEL_DETAIL}?eid=6148&instance=2026-7-9",
        body=fixture_text("geisel_detail.html"),
        content_type="text/html",
    )

    scan = GeiselSource(HttpClient(attempts=1), workers=1).scan(date(2026, 7, 5), date(2026, 7, 12))

    assert len(scan.events) == 1
    event = scan.events[0]
    assert event.start_date == date(2026, 7, 9)
    assert event.location == "DHMC Auditorium H, 1 Medical Center Drive, Lebanon, NH"
    assert event.sponsor == "Biomedical Data Science"
    assert event.categories == ("Grand Rounds", "Lecture/Seminar")
    assert "light lunch" in event.description.lower()


@responses.activate
def test_dartmouth_groups_paginates_and_enriches_detail_pages() -> None:
    responses.get(
        LIST_URL,
        body=fixture_text("dartmouth_groups_page_1.json"),
        content_type="application/json",
    )
    responses.get(
        LIST_URL,
        body=fixture_text("dartmouth_groups_page_2.json"),
        content_type="application/json",
    )
    responses.get(
        f"{GROUPS_DETAIL}?id=1630485",
        body=fixture_text("dartmouth_groups_detail.html"),
        content_type="text/html",
    )
    responses.get(
        f"{GROUPS_DETAIL}?id=1630604",
        body=fixture_text("dartmouth_groups_tea.html"),
        content_type="text/html",
    )

    scan = DartmouthGroupsSource(
        HttpClient(attempts=1), workers=1, page_size=1
    ).scan(date(2026, 7, 1), date(2026, 7, 22))

    assert scan.complete
    assert len(scan.events) == 2
    picnic = next(
        event
        for event in scan.events
        if event.source_keys == ("dartmouth-groups:1630485",)
    )
    assert picnic.start == datetime(2026, 7, 9, 12, 0, tzinfo=picnic.start.tzinfo)
    assert picnic.end == datetime(2026, 7, 9, 13, 0, tzinfo=picnic.end.tzinfo)
    assert picnic.location == "BEMA, Dartmouth College, Hanover, NH"
    assert picnic.sponsor == (
        "Student Wellness Center at Dartmouth / Office of Pluralism and Leadership"
    )
    assert picnic.categories == ("Social", "free food")
    assert "Food Provided" in picnic.description
    assert "https://forms.example.edu/picnic" in picnic.urls
