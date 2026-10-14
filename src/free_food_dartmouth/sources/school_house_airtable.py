"""Import School House events from a freshly exported public Airtable iCalendar file."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from icalendar import Calendar

from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import easternize, unique

SOURCE_NAME = "School House Airtable"
SHARED_VIEW_URL = "https://airtable.com/appIAfygGZFs7eJr6/shrSKjBHwNBId5Mjx/tblWCjX1JWEWWcuuQ"
EXPORT_ENV_VAR = "SCHOOL_HOUSE_AIRTABLE_ICS"
CANCELLED = re.compile(r"^\s*(?:cancell?ed|postponed)\b", re.IGNORECASE)
COPY_SUFFIX = re.compile(r"(?:\s+copy)+\s*$", re.IGNORECASE)


class SchoolHouseAirtableSource:
    def __init__(self, path: Path | None = None) -> None:
        value = os.getenv(EXPORT_ENV_VAR, "")
        self.path = path if path is not None else Path(value) if value else None

    def scan(self, start: date, end: date) -> SourceScan:
        if self.path is None:
            raise RuntimeError(
                f"{EXPORT_ENV_VAR} is not set: refusing an apparently complete scan "
                "without a fresh Airtable export"
            )
        payload = self.path.read_bytes()
        if not payload.lstrip().startswith(b"BEGIN:VCALENDAR"):
            raise ValueError("School House Airtable export is not an iCalendar file")
        calendar = Calendar.from_ical(payload)
        components = calendar.walk("VEVENT")
        if not components:
            raise ValueError("School House Airtable export contains no VEVENT records")

        events: list[EventRecord] = []
        errors: list[str] = []
        for component in components:
            try:
                event = self._event(component)
                if event is not None and start <= event.start_date < end:
                    events.append(event)
            except Exception as exc:
                uid = str(component.get("uid", "unknown"))
                errors.append(f"{uid}: {exc}")
        return SourceScan(SOURCE_NAME, tuple(events), complete=not errors, errors=tuple(errors))

    @staticmethod
    def _event(component: object) -> EventRecord | None:
        if not hasattr(component, "decoded") or not hasattr(component, "get"):
            raise TypeError("invalid iCalendar event")
        get = component.get
        decoded = component.decoded
        title = str(get("summary", "")).strip()
        if not title:
            raise ValueError("missing event title")
        status = str(get("status", "")).upper()
        if status == "CANCELLED" or CANCELLED.match(title):
            return None
        uid = str(get("uid", "")).strip()
        if not uid:
            raise ValueError("missing Airtable record UID")
        start = easternize(decoded("dtstart"))
        if get("dtend") is not None:
            end = easternize(decoded("dtend"))
        else:
            end = start + (timedelta(hours=1) if isinstance(start, datetime) else timedelta(days=1))
        if end <= start:
            raise ValueError("event ends before it starts")

        # Airtable's public ICS puts a record link in DESCRIPTION instead of event details.
        # Keep the link for attribution; do not treat its URL as evidence of free food.
        record_link = str(get("description", "")).strip()
        urls = (
            [record_link, SHARED_VIEW_URL]
            if record_link.startswith(("https://airtable.com/", "http://airtable.com/"))
            else [SHARED_VIEW_URL]
        )
        title = COPY_SUFFIX.sub("", title).strip()
        record_id = uid.split("@", 1)[0]
        occurrence = start.isoformat()
        source_key = f"school-house-airtable:{record_id}:{occurrence}"
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description="",
            summary="",
            sponsor="School House",
            location=str(get("location", "")).strip(),
            urls=unique(urls),
            categories=("House Community", "School House"),
            source_keys=(source_key,),
            sources=(SOURCE_NAME,),
            uid_key=source_key,
        )
