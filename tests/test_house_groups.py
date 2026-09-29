from datetime import date, datetime

import responses
from conftest import fixture_text

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.sources.house_groups import (
    HOUSE_CALENDARS,
    DartmouthHouseCalendarsSource,
)
from free_food_dartmouth.utils import EASTERN


def test_house_group_calendar_list_covers_all_six_houses() -> None:
    assert [(house.name, house.club_id) for house in HOUSE_CALENDARS] == [
        ("Allen House", "67704"),
        ("East Wheelock House", "67705"),
        ("North Park House", "67707"),
        ("School House", "67709"),
        ("South House", "67710"),
        ("West House", "67711"),
    ]


@responses.activate
def test_house_group_calendars_parse_public_ics_feeds() -> None:
    body = fixture_text("house_groups.ics")
    for house in HOUSE_CALENDARS:
        responses.get(house.ics_url, body=body, content_type="text/calendar")

    scan = DartmouthHouseCalendarsSource(HttpClient(attempts=1)).scan(
        date(2026, 9, 29), date(2026, 10, 20)
    )

    assert scan.complete
    assert len(scan.events) == 12
    allen_dinner = next(
        event
        for event in scan.events
        if event.sponsor == "Allen House" and event.title == "Community Dinner"
    )
    assert allen_dinner.start == datetime(2026, 10, 4, 18, 0, tzinfo=EASTERN)
    assert allen_dinner.end == datetime(2026, 10, 4, 19, 30, tzinfo=EASTERN)
    assert allen_dinner.source_keys == ("house-groups:67704:house-dinner-20261004",)
    assert "https://dartmouthgroups.dartmouth.edu/event/example" in allen_dinner.urls
    assert "explicit food-service wording" in match_event(allen_dinner)

    west_meeting = next(
        event
        for event in scan.events
        if event.sponsor == "West House" and event.title == "House Council"
    )
    assert match_event(west_meeting) == ()
