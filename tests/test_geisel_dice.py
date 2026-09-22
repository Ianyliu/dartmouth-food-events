from datetime import date, datetime, timedelta

import responses
from conftest import fixture_text

from free_food_dartmouth.dedupe import deduplicate
from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.sources.geisel import DICE_URL, GeiselDiceSource
from free_food_dartmouth.utils import EASTERN


@responses.activate
def test_geisel_dice_scan_reads_upcoming_events_page() -> None:
    responses.get(DICE_URL, body=fixture_text("geisel_dice.html"), content_type="text/html")

    scan = GeiselDiceSource(HttpClient(attempts=1)).scan(
        date(2026, 9, 14), date(2026, 9, 23)
    )

    assert scan.complete
    assert len(scan.events) == 2

    social = next(event for event in scan.events if event.title.startswith("One Campus"))
    assert social.start == datetime(2026, 9, 15, 17, 0, tzinfo=EASTERN)
    assert social.end == datetime(2026, 9, 15, 18, 0, tzinfo=EASTERN)
    assert social.location == "Whaleback Mountain, Enfield, NH"
    assert social.sponsor == "DICE Office"
    assert "free food" in social.description.lower()
    assert "https://dartmouth.co1.qualtrics.com/jfe/form/social" in social.urls
    assert "explicit food-service wording" in match_event(social)

    women = next(event for event in scan.events if event.title.startswith("Women:"))
    assert women.start == datetime(2026, 9, 22, 17, 30, tzinfo=EASTERN)
    assert women.end == datetime(2026, 9, 22, 21, 0, tzinfo=EASTERN)
    assert women.location == "Artists For Humanity, 100 W 2nd St, Boston, MA"


def test_geisel_dice_time_range_infers_missing_meridiem() -> None:
    start, end, _ = GeiselDiceSource._date_time_location(
        "September 22, 2026 | 11 - 1 PM | Hanover, NH"
    )
    assert start == datetime(2026, 9, 22, 11, 0, tzinfo=EASTERN)
    assert end == datetime(2026, 9, 22, 13, 0, tzinfo=EASTERN)


def test_shared_dice_landing_page_does_not_force_deduplication() -> None:
    start = datetime(2026, 9, 22, 17, 30, tzinfo=EASTERN)
    first = EventRecord(
        "Leadership Reception",
        start,
        start + timedelta(hours=1),
        "",
        urls=(DICE_URL,),
    )
    second = EventRecord(
        "Community Research Workshop",
        start,
        start + timedelta(hours=1),
        "",
        urls=(DICE_URL,),
    )

    assert len(deduplicate([first, second])) == 2
