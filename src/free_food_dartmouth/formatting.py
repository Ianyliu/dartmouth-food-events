from __future__ import annotations

from free_food_dartmouth.models import EventRecord


def calendar_description(event: EventRecord) -> str:
    if event.calendar_description:
        return event.calendar_description
    sections: list[str] = []
    if event.urls:
        sections.append("Original event page(s):\n" + "\n".join(event.urls))
    if event.description:
        sections.append("Description:\n" + event.description)
    if event.sponsor:
        sections.append("Sponsor / organizer: " + event.sponsor)
    if event.audience:
        sections.append("Audience: " + event.audience)
    if event.sources:
        sections.append("Source: " + ", ".join(event.sources))
    if event.match_reasons:
        sections.append("Why this was included: " + "; ".join(event.match_reasons))
    sections.append(
        "Food availability is inferred from the source listing; verify details before attending."
    )
    return "\n\n".join(sections)
