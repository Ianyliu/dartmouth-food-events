from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime

from rapidfuzz import fuzz

from free_food_dartmouth.models import DateValue, EventRecord

DEGREE_WORDS = re.compile(r"\b(md|phd|mph|facc|faha|do|ms|ma)\b", re.IGNORECASE)
NON_WORD = re.compile(r"[^a-z0-9]+")


def _normal_title(value: str) -> str:
    value = value.casefold().replace("dcc", "dartmouth cancer center")
    value = DEGREE_WORDS.sub(" ", value)
    return NON_WORD.sub(" ", value).strip()


def _same_start(left: DateValue, right: DateValue) -> bool:
    if isinstance(left, datetime) and isinstance(right, datetime):
        return abs((left - right).total_seconds()) <= 300
    if isinstance(left, datetime) or isinstance(right, datetime):
        return False
    return left == right


def _external_urls(event: EventRecord) -> set[str]:
    return {
        url.rstrip("/")
        for url in event.urls
        if "home.dartmouth.edu/events/event" not in url
        and "geiselmed.dartmouth.edu/calendar/event_view" not in url
    }


def same_event(left: EventRecord, right: EventRecord) -> bool:
    if set(left.source_keys) & set(right.source_keys):
        return True
    if not _same_start(left.start, right.start):
        return False
    if _external_urls(left) & _external_urls(right):
        return True
    return fuzz.token_set_ratio(_normal_title(left.title), _normal_title(right.title)) >= 82


def _unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _best_title(left: str, right: str) -> str:
    return max((left, right), key=lambda value: (len(_normal_title(value).split()), len(value)))


def merge_events(left: EventRecord, right: EventRecord) -> EventRecord:
    description = max((left.description, right.description), key=len)
    summary = max((left.summary, right.summary), key=len)
    location = max((left.location, right.location), key=len)
    sponsor = " / ".join(_unique([left.sponsor, right.sponsor]))
    audience = " / ".join(_unique([left.audience, right.audience]))
    uid_key = left.uid_key or right.uid_key or min((*left.source_keys, *right.source_keys))
    start: date | datetime = left.start
    end: date | datetime = left.end
    if left.all_day and not right.all_day:
        start, end = right.start, right.end
    return replace(
        left,
        title=_best_title(left.title, right.title),
        start=start,
        end=end,
        description=description,
        summary=summary,
        location=location,
        sponsor=sponsor,
        audience=audience,
        urls=_unique([*left.urls, *right.urls]),
        categories=_unique([*left.categories, *right.categories]),
        source_keys=_unique([*left.source_keys, *right.source_keys]),
        sources=_unique([*left.sources, *right.sources]),
        match_reasons=_unique([*left.match_reasons, *right.match_reasons]),
        uid_key=uid_key,
    )


def deduplicate(events: list[EventRecord]) -> list[EventRecord]:
    groups: list[EventRecord] = []
    for event in sorted(events, key=lambda item: (str(item.start), item.title.casefold())):
        for index, existing in enumerate(groups):
            if same_event(existing, event):
                groups[index] = merge_events(existing, event)
                break
        else:
            groups.append(event)
    return groups
