from datetime import datetime, timedelta

from free_food_dartmouth.matcher import match_event
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.utils import EASTERN


def event(
    title: str,
    description: str = "",
    categories: tuple[str, ...] = (),
    summary: str = "",
) -> EventRecord:
    start = datetime(2026, 7, 9, 12, tzinfo=EASTERN)
    return EventRecord(
        title,
        start,
        start + timedelta(hours=1),
        description,
        summary=summary,
        categories=categories,
    )


def test_free_food_category_always_matches() -> None:
    assert "Free Food category" in match_event(event("Lecture", categories=("Free Food",)))


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


def test_food_subject_without_service_context_does_not_match() -> None:
    assert not match_event(
        event(
            "Public Figure",
            summary="A show about babyccinos, a drink you won't be able to forget.",
        )
    )


def test_food_in_summary_with_service_context_matches() -> None:
    assert match_event(
        event(
            "Community Gathering",
            summary="Pizza and snacks will be available for attendees.",
        )
    )


def test_common_event_service_phrases_match() -> None:
    assert match_event(event("Documentary", summary="Join colleagues for a lunch screening."))
    assert match_event(event("Community Walk", "Followed by a coffee or tea break at Ramekin."))
    assert match_event(event("Celebration", "We are hosting a meal for students."))
    assert match_event(event("Festival", "Complete with local food trucks and Kona Ice."))
