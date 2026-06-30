from datetime import datetime, timedelta

from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.utils import EASTERN


def event(title: str, description: str = "", categories: tuple[str, ...] = ()) -> EventRecord:
    start = datetime(2026, 7, 9, 12, tzinfo=EASTERN)
    return EventRecord(title, start, start + timedelta(hours=1), description, categories=categories)


def test_free_food_category_always_matches() -> None:
    assert "Dartmouth Free Food category" in match_event(
        event("Lecture", categories=("Free Food",))
    )


def test_explicit_food_service_matches() -> None:
    assert match_event(event("Seminar", "A light lunch will be provided first-come, first-served."))


def test_food_in_title_matches() -> None:
    assert match_event(event("Pizza Retreat"))


def test_food_topic_and_bring_your_own_are_excluded() -> None:
    assert not match_event(event("Food Systems Research Seminar", "Bring your lunch."))
    assert not match_event(
        event("Nutrition Research", "Dietary research methods and food science.")
    )


def test_explicit_provision_overrides_generic_exclusion() -> None:
    assert match_event(event("Food Systems Talk", "A complimentary lunch will be provided."))
