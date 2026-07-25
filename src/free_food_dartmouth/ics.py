from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from icalendar import Calendar, Event, Timezone

from free_food_dartmouth.formatting import calendar_description
from free_food_dartmouth.models import EventRecord
from free_food_dartmouth.utils import EASTERN

CALENDAR_NAME = "Free Food @Dartmouth"
FEED_URL = "https://ianyliu.github.io/dartmouth-food-events/free-food-dartmouth.ics"


def build_calendar(events: list[EventRecord], generated_at: datetime) -> Calendar:
    calendar = Calendar()  # type: ignore[no-untyped-call]
    calendar.add("prodid", "-//Ianyliu//Free Food @Dartmouth//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", CALENDAR_NAME)
    calendar.add("x-wr-timezone", "America/New_York")
    calendar.add("x-published-ttl", "PT6H")
    calendar.add(
        "refresh-interval",
        timedelta(hours=6),
        parameters={"VALUE": "DURATION"},
    )
    calendar.add_component(
        Timezone.from_tzinfo(
            EASTERN,
            tzid="America/New_York",
            first_date=date(2020, 1, 1),
            last_date=date(2040, 1, 1),
        )
    )
    for item in sorted(events, key=lambda value: (str(value.start), value.title.casefold())):
        component = Event()  # type: ignore[no-untyped-call]
        uid_key = item.uid_key or (item.source_keys[0] if item.source_keys else item.title)
        component.add("uid", f"{_safe_uid(uid_key)}@free-food-dartmouth")
        component.add("dtstamp", generated_at)
        component.add("last-modified", generated_at)
        component.add("sequence", 0)
        component.add("summary", item.title)
        component.add("dtstart", item.start)
        component.add("dtend", item.end)
        component.add("description", calendar_description(item))
        if item.location:
            component.add("location", item.location)
        if item.primary_url:
            component.add("url", item.primary_url)
        component.add("status", "TENTATIVE" if item.tentative else "CONFIRMED")
        component.add("class", "PUBLIC")
        component.add("transp", "TRANSPARENT")
        component.add("x-microsoft-cdo-busystatus", "FREE")
        calendar.add_component(component)
    return calendar


def write_outputs(output_dir: Path, events: list[EventRecord], generated_at: datetime) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    calendar = build_calendar(events, generated_at)
    (output_dir / "free-food-dartmouth.ics").write_bytes(calendar.to_ical())
    generated = generated_at.astimezone(EASTERN).strftime("%B %-d, %Y at %-I:%M %p %Z")
    index = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(CALENDAR_NAME)}</title>
  <style>
    body {{
      max-width: 44rem; margin: 4rem auto; padding: 0 1.25rem;
      font: 1.05rem/1.6 system-ui, sans-serif; color: #173b2b;
    }}
    h1 {{ color: #00693e; }}
    a {{ color: #00693e; font-weight: 650; }}
    .meta {{ color: #52665d; }}
  </style>
</head>
<body>
  <h1>{html.escape(CALENDAR_NAME)}</h1>
  <p>
    A rolling three-week calendar of Dartmouth, Geisel, Dartmouth Groups, and
    Guarini events likely to offer food.
  </p>
  <p><a href="free-food-dartmouth.ics">Subscribe to or download the calendar</a></p>
  <p>
    Outlook: choose <strong>Add calendar → Subscribe from web</strong>, then paste
    <code>{html.escape(FEED_URL)}</code>. Subscribing receives future updates; importing
    the file is a one-time copy.
  </p>
  <p class="meta">{len(events)} events · Updated {html.escape(generated)}</p>
  <p class="meta">
    Food availability is inferred. Verify the original event listing before attending.
  </p>
</body>
</html>
"""
    (output_dir / "index.html").write_text(index, encoding="utf-8")


def _safe_uid(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
