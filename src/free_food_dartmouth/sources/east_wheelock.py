from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, quote, urlparse

from bs4 import BeautifulSoup
from icalendar import Calendar

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import easternize, unique

HOME_URL = "https://www.ewhousedartmouth.com/"
SOURCE_NAME = "East Wheelock House"


class EastWheelockSource:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def scan(self, start: date, end: date) -> SourceScan:
        homepage = self.client.get(HOME_URL)
        calendar_id = self._calendar_id(homepage.text)
        ics_url = (
            "https://calendar.google.com/calendar/ical/"
            f"{quote(calendar_id, safe='')}/public/basic.ics"
        )
        response = self.client.get(ics_url)
        calendar = Calendar.from_ical(response.content)

        events: list[EventRecord] = []
        failures: list[str] = []
        for component in calendar.walk("VEVENT"):
            try:
                event = self._event(component, ics_url)
                if start <= event.start_date < end:
                    events.append(event)
            except Exception as exc:
                uid = str(component.get("uid", "unknown event"))
                failures.append(f"{uid}: {exc}")
        return SourceScan(
            SOURCE_NAME,
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    @staticmethod
    def _calendar_id(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for iframe in soup.select('iframe[src*="calendar.google.com/calendar"]'):
            src = str(iframe.get("src", ""))
            values = parse_qs(urlparse(src).query).get("src", [])
            for value in values:
                if value.strip():
                    return value.strip()
        raise ValueError("missing East Wheelock public Google Calendar embed")

    @staticmethod
    def _event(component: object, ics_url: str) -> EventRecord:
        if not hasattr(component, "decoded") or not hasattr(component, "get"):
            raise TypeError("invalid iCalendar event component")
        decoded = component.decoded  # type: ignore[attr-defined]
        get = component.get  # type: ignore[attr-defined]

        raw_start = decoded("dtstart")
        raw_end = decoded("dtend") if get("dtend") is not None else None
        start = easternize(raw_start)
        if raw_end is None:
            end = start + (timedelta(hours=1) if isinstance(start, datetime) else timedelta(days=1))
        else:
            end = easternize(raw_end)

        title = str(get("summary", "")).strip()
        if not title:
            raise ValueError("missing event title")
        description = str(get("description", "")).strip()
        location = str(get("location", "")).strip()
        uid = str(get("uid", "")).strip()
        if not uid:
            raise ValueError("missing event UID")

        urls = [HOME_URL, ics_url]
        event_url = str(get("url", "")).strip()
        if event_url.startswith(("http://", "https://")):
            urls.insert(0, event_url)

        source_key = f"east-wheelock:{uid}"
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=description.split("\n", 1)[0][:500],
            location=location,
            sponsor=SOURCE_NAME,
            urls=unique(urls),
            categories=("House Community", SOURCE_NAME),
            source_keys=(source_key,),
            sources=(SOURCE_NAME,),
            uid_key=source_key,
        )
