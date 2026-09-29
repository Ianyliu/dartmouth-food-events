from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from icalendar import Calendar

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import easternize, unique


@dataclass(frozen=True, slots=True)
class HouseGroupCalendar:
    name: str
    club_id: str

    @property
    def ics_url(self) -> str:
        return f"https://dartmouthgroups.dartmouth.edu/ical/dartmouth/ical_club_{self.club_id}.ics"


HOUSE_CALENDARS = (
    HouseGroupCalendar("Allen House", "67704"),
    HouseGroupCalendar("East Wheelock House", "67705"),
    HouseGroupCalendar("North Park House", "67707"),
    HouseGroupCalendar("School House", "67709"),
    HouseGroupCalendar("South House", "67710"),
    HouseGroupCalendar("West House", "67711"),
)

SOURCE_NAME = "Dartmouth House Calendars"


class DartmouthHouseCalendarsSource:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def scan(self, start: date, end: date) -> SourceScan:
        events: list[EventRecord] = []
        failures: list[str] = []
        for house in HOUSE_CALENDARS:
            try:
                response = self.client.get(house.ics_url)
                calendar = Calendar.from_ical(response.content)
                for component in calendar.walk("VEVENT"):
                    event = self._event(house, component)
                    if start <= event.start_date < end:
                        events.append(event)
            except Exception as exc:
                failures.append(f"{house.name}: {exc}")

        return SourceScan(
            SOURCE_NAME,
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    @staticmethod
    def _event(house: HouseGroupCalendar, component: object) -> EventRecord:
        if not hasattr(component, "decoded") or not hasattr(component, "get"):
            raise TypeError("invalid iCalendar event component")
        decoded = component.decoded
        get = component.get

        raw_start = decoded("dtstart")
        start = easternize(raw_start)
        if get("dtend") is not None:
            end = easternize(decoded("dtend"))
        else:
            end = start + (timedelta(hours=1) if isinstance(start, datetime) else timedelta(days=1))

        title = str(get("summary", "")).strip()
        if not title:
            raise ValueError("missing event title")
        uid = str(get("uid", "")).strip()
        if not uid:
            raise ValueError("missing event UID")

        description = str(get("description", "")).strip()
        location = str(get("location", "")).strip()
        event_url = str(get("url", "")).strip()
        urls = [house.ics_url]
        if event_url.startswith(("http://", "https://")):
            urls.insert(0, event_url)

        source_key = f"house-groups:{house.club_id}:{uid}"
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=description.split("\n", 1)[0][:500],
            location=location,
            sponsor=house.name,
            urls=unique(urls),
            categories=("House Community", house.name, "Dartmouth Groups"),
            source_keys=(source_key,),
            sources=(SOURCE_NAME, house.name),
            uid_key=source_key,
        )
