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


def test_allen_house_snack_and_food_break_match() -> None:
    # Regression test for Allen House Groups events that the published
    # feed missed entirely: "serving up a new snack" and "for food".
    assert match_event(
        event(
            "Bites in Bisco",
            "We'll be in Bisco lounge every week serving up a new snack-- just for you.",
        )
    )
    assert match_event(
        event(
            "Sundays in Streeter",
            "meet you down in Streeter basement for food and a break from studying :)",
        )
    )


def test_dinner_and_discussion_matches() -> None:
    # South House dinner-and-discussion events (Risam, Chuck Sams)
    # only match once their own descriptions are parsed; the old
    # shifted descriptions matched by borrowing the next event's text.
    assert match_event(
        event(
            "SxSH: Data, Power, and Inequality: A Conversation with Prof. Roopika Risam",
            "Join South and East Wheelock Houses for a dinner and discussion "
            "with Prof. Roopika Risam.",
        )
    )
    assert match_event(
        event(
            "Being a Public Advocate for the Earth: An Evening with Chuck Sams",
            "Join South and School Houses for a dinner and discussion with Chuck Sams.",
        )
    )


def test_for_some_pastries_coffee_tea_matches() -> None:
    # South House International Student Appreciation (Week 7):
    # "for some pastries, coffee, and tea" has no service-context
    # word like "served" nearby, so it needs the explicit pattern.
    assert match_event(
        event(
            "International Student Appreciation",
            "Please join the House Communities for some pastries, coffee, "
            "and tea in recognition of international education week.",
        )
    )


def test_school_house_waffles_and_pastries_are_food_matches() -> None:
    assert match_event(event("Waffle Wellness Study Break"))
    assert match_event(event("School Grounds - Free coffee & pastries"))


def test_provide_and_joining_us_and_on_hand_are_service_context() -> None:
    # Regression tests for the Nov 22, 2026 audit: four events the
    # published feed missed because their food-service wording did not
    # match any SERVICE_CONTEXT term.
    # Guarini "Snow Globe Making" (Dec 3): "we will provide ...
    # hot chocolate and other refreshments" — "provide" (present
    # tense) was not covered, only "provided".
    assert match_event(
        event(
            "Snow Globe Making",
            "Join your Guarini peers for a cozy winter craft! We will provide "
            "all the supplies to make a snow globe along with some hot "
            "chocolate and other refreshments.",
        )
    )
    # DCAL "Grading Co-Work Café 2" (Nov 30): "snacks and caffeine
    # on hand" — "on hand" was not a service-context term.
    assert match_event(
        event(
            "Grading Co-Work Café 2",
            "Get your grading done in the company of others doing the same, "
            "and with the necessary supports of snacks and caffeine on hand.",
        )
    )
    # DCAL "Course Design Co-Work Café 1/2" (Dec 2, Dec 8): "joining
    # us in DCAL (with the good snacks ...)" — only "join us for"
    # was covered, not "joining us".
    assert match_event(
        event(
            "Course Design Co-Work Café 1",
            "Find camaraderie and accountability among colleagues preparing "
            "winter courses and syllabi by joining us in DCAL (with the "
            "good snacks, natural light, and espresso machine) for an "
            "afternoon course design co-work café!",
        )
    )
