from __future__ import annotations

import re

from free_food_dartmouth.models import EventRecord

FOOD_TERMS = re.compile(
    r"\b(food|meal|bbq|barbecue|cookout|lunch|dinner|breakfast|brunch|pizza|snacks?|"
    r"dessert|ice cream|cake|cookies?|pies?|candy|chocolate|coffee|tea|drinks?|beverage|"
    r"beer|wine|cocktails?|mocktails?|refreshments?|popcorn|dole whip)\b",
    re.IGNORECASE,
)
EXPLICIT_FOOD = re.compile(
    r"\b(?:free|complimentary)\s+(?:food|meal|lunch|dinner|breakfast|snacks?|refreshments?)\b|"
    r"\b(?:food|meal|lunch|dinner|breakfast|snacks?|refreshments?)\s+"
    r"(?:will\s+be\s+|is\s+)?(?:provided|served|available)\b|"
    r"\b(?:light\s+lunch|lunch\s+will\s+be\s+provided|pizza\s+(?:will\s+be\s+)?provided|"
    r"reception\s+(?:immediately\s+)?following|join\s+us\s+for\s+(?:lunch|dinner|breakfast|"
    r"brunch|pizza|refreshments))\b",
    re.IGNORECASE,
)
SERVICE_CONTEXT = re.compile(
    r"\b(provided|served|available|complimentary|free|first[- ]come|while supplies last|"
    r"join us for|enjoy|reception|social|mixer)\b",
    re.IGNORECASE,
)
EXCLUSIONS = re.compile(
    r"\b(closed for lunch|bring your (?:own )?lunch|brown[ -]bag lunch|"
    r"food will not be provided|no food (?:will be )?(?:provided|served)|"
    r"refreshments will not be served|food systems?|food insecurity|food science|"
    r"dietary research|nutrition research)\b",
    re.IGNORECASE,
)


def _nearby_context(text: str) -> bool:
    for food_match in FOOD_TERMS.finditer(text):
        start = max(0, food_match.start() - 90)
        end = min(len(text), food_match.end() + 90)
        if SERVICE_CONTEXT.search(text[start:end]):
            return True
    return False


def match_event(event: EventRecord) -> tuple[str, ...]:
    title_summary = " ".join((event.title, event.summary)).strip()
    full_text = " ".join((title_summary, event.description)).strip()
    category_match = any(category.casefold() == "free food" for category in event.categories)

    if EXCLUSIONS.search(full_text) and not category_match and not EXPLICIT_FOOD.search(full_text):
        return ()

    reasons: list[str] = []
    if category_match:
        reasons.append("Free Food category")
    if EXPLICIT_FOOD.search(full_text):
        reasons.append("explicit food-service wording")
    if FOOD_TERMS.search(title_summary):
        reasons.append("food or meal keyword in title/summary")
    elif _nearby_context(event.description):
        reasons.append("food keyword near service context")

    return tuple(dict.fromkeys(reasons))
