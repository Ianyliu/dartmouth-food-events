from datetime import datetime, timedelta

from free_food_dartmouth.dedupe import deduplicate
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.utils import EASTERN


def test_cross_source_duplicates_merge_and_retain_links() -> None:
    start = datetime(2026, 6, 30, 12, tzinfo=EASTERN)
    dartmouth = EventRecord(
        "Dartmouth Cancer Center Grand Rounds - S. Brown",
        start,
        start + timedelta(hours=1),
        "Short description",
        sponsor="Dartmouth Cancer Center",
        urls=("https://home.dartmouth.edu/events/event?event=123",),
        source_keys=("dartmouth:123",),
        sources=("Dartmouth",),
        uid_key="dartmouth:123",
    )
    geisel = EventRecord(
        "DCC Grand Rounds with Sherry-Ann Brown, MD, PhD",
        start,
        start + timedelta(hours=1),
        "A much longer seminar description with speaker details.",
        location="DHMC Auditorium E",
        urls=("https://geiselmed.dartmouth.edu/calendar/event_view.php?eid=1&instance=2026-6-30",),
        source_keys=("geisel:1:2026-6-30",),
        sources=("Geisel",),
        uid_key="geisel:1:2026-6-30",
    )

    merged = deduplicate([dartmouth, geisel])

    assert len(merged) == 1
    assert set(merged[0].source_keys) == {"dartmouth:123", "geisel:1:2026-6-30"}
    assert len(merged[0].urls) == 2
    assert merged[0].location == "DHMC Auditorium E"
    assert merged[0].description == geisel.description


def test_merge_prefers_later_end_and_real_location() -> None:
    # Dartmouth Groups ends are often truncated to one hour and its
    # location field is an auth-gated placeholder; a merge with a
    # newsletter source carrying the full end and a real location must
    # keep the full end and the real location, not the placeholder.
    start = datetime(2026, 10, 28, 17, 30, tzinfo=EASTERN)
    groups = EventRecord(
        "Doing Well by Doing Good: A Dinner and Discussion",
        start,
        start + timedelta(hours=1),
        "Groups description",
        location="Sign in to download the location",
        source_keys=("house-groups:67710:doing-well",),
        sources=("Dartmouth House Calendars",),
        uid_key="house-groups:67710:doing-well",
    )
    newsletter = EventRecord(
        "Doing Well by Doing Good: A Dinner and Discussion",
        start,
        start + timedelta(hours=2),
        "Newsletter description",
        location="Fayerweather Great Hall",
        source_keys=("south-house:2026-10-28:1730:doing-well",),
        sources=("South House",),
        uid_key="south-house:2026-10-28:1730:doing-well",
    )
    merged = deduplicate([groups, newsletter])
    assert len(merged) == 1
    assert merged[0].end == start + timedelta(hours=2)
    assert merged[0].location == "Fayerweather Great Hall"


def test_same_title_at_different_times_does_not_merge() -> None:
    start = datetime(2026, 7, 1, 12, tzinfo=EASTERN)
    first = EventRecord("Lunch", start, start + timedelta(hours=1), "")
    second = EventRecord("Lunch", start + timedelta(hours=2), start + timedelta(hours=3), "")
    assert len(deduplicate([first, second])) == 2
