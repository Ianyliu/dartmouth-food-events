from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser
from icalendar import Calendar

from free_food_dartmouth.http import HttpClient, SourceFetchError
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, clean_html, easternize, unique

BASE_URL = "https://home.dartmouth.edu"
SEARCH_URL = f"{BASE_URL}/events/ajax/search"
DETAIL_URL = f"{BASE_URL}/events/event"
ICS_URL = "https://events.dartmouth.edu/events/{event_id}/export.ics"
EVENT_ID = re.compile(r"(?:\?|&)event=(\d+)")


class DartmouthSource:
    def __init__(self, client: HttpClient | None = None, workers: int = 6) -> None:
        self.client = client or HttpClient()
        self.workers = workers

    def scan(self, start: date, end: date) -> SourceScan:
        ids = self._event_ids(start, end)
        events: list[EventRecord] = []
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {executor.submit(self._event, event_id): event_id for event_id in ids}
            for future in as_completed(futures):
                event_id = futures[future]
                try:
                    event = future.result()
                    if event is not None and start <= event.start_date < end:
                        events.append(event)
                except Exception as exc:
                    failures.append(f"{event_id}: {exc}")
        if failures:
            raise SourceFetchError(
                f"Dartmouth detail scan incomplete ({len(failures)} failures): "
                + "; ".join(failures[:3])
            )
        return SourceScan("Dartmouth", tuple(events))

    def _event_ids(self, start: date, end: date) -> list[str]:
        limit = 100
        offset = 0
        ids: list[str] = []
        while True:
            response = self.client.get(
                SEARCH_URL,
                params={
                    "begin": start.isoformat(),
                    "end": (end - timedelta(days=1)).isoformat(),
                    "offset": offset,
                    "limit": limit,
                },
            )
            commands = response.json()
            content = next(
                (
                    command.get("content", "")
                    for command in commands
                    if command.get("command") == "eventsContent"
                ),
                "",
            )
            soup = BeautifulSoup(str(content), "html.parser")
            page_ids: list[str] = []
            for link in soup.select("a.event-teaser__title-link[href]"):
                match = EVENT_ID.search(str(link.get("href", "")))
                if match:
                    page_ids.append(match.group(1))
            ids.extend(page_ids)
            next_link = soup.select_one("a.events__next-link")
            if (
                len(page_ids) < limit
                or next_link is None
                or "disabled" in next_link.get_attribute_list("class")
            ):
                break
            offset += limit
        return list(dict.fromkeys(ids))

    def _event(self, event_id: str) -> EventRecord | None:
        detail_url = f"{DETAIL_URL}?event={event_id}"
        response = self.client.get(detail_url)
        soup = BeautifulSoup(response.text, "html.parser")
        data = self._json_ld(soup)
        if not data:
            return None

        component: Any | None = None
        try:
            calendar_response = self.client.get(ICS_URL.format(event_id=event_id))
            calendar = Calendar.from_ical(calendar_response.content)
            component = next((item for item in calendar.walk() if item.name == "VEVENT"), None)
        except (SourceFetchError, ValueError):
            component = None
        if component is None:
            start, end = self._fallback_times(data, soup)
        else:
            start = easternize(component.decoded("DTSTART"))
            end = easternize(component.decoded("DTEND"))

        categories = unique(
            [link.get_text(" ", strip=True) for link in soup.select(".news-event--category a")]
        )
        urls = [detail_url]
        for anchor in soup.select(".news-event--body a[href]"):
            href = str(anchor.get("href", ""))
            if href.startswith(("http://", "https://")):
                urls.append(href)
        raw_location = data.get("location")
        location_data: dict[str, Any] = raw_location if isinstance(raw_location, dict) else {}
        location = str(location_data.get("name", ""))
        description = clean_html(str(data.get("description", "")))
        summary = clean_html(str(data.get("about", "")))
        component_summary = component.get("SUMMARY", "") if component is not None else ""
        component_location = component.get("LOCATION", "") if component is not None else ""
        return EventRecord(
            title=clean_html(str(data.get("name", component_summary))),
            start=start,
            end=end,
            description=description or summary,
            summary=summary,
            location=location or str(component_location),
            sponsor=clean_html(str(data.get("funder", ""))),
            audience=clean_html(str(data.get("audience", ""))),
            urls=unique(urls),
            categories=categories,
            source_keys=(f"dartmouth:{event_id}",),
            sources=("Dartmouth",),
            uid_key=f"dartmouth:{event_id}",
        )

    @staticmethod
    def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            if not isinstance(script, Tag) or not script.string:
                continue
            parsed = json.loads(script.string)
            candidates = parsed if isinstance(parsed, list) else [parsed]
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("@type") == "Event":
                    return candidate
        return {}

    @staticmethod
    def _fallback_times(
        data: dict[str, Any], soup: BeautifulSoup
    ) -> tuple[date | datetime, date | datetime]:
        raw_start = str(data.get("startDate", "")).strip()
        time_node = soup.select_one(".news-event--time .news-event--meta__item--text")
        time_text = time_node.get_text(" ", strip=True) if time_node else ""
        if raw_start:
            parsed = date_parser.isoparse(raw_start)
            if len(raw_start) <= 10 or "all day" in time_text.casefold():
                event_date = parsed.date()
                return event_date, event_date + timedelta(days=1)
            start = easternize(parsed)
            assert isinstance(start, datetime)
        else:
            date_node = soup.select_one(".news-event--date .news-event--meta__item--text")
            if date_node is None:
                raise ValueError("event has neither ICS nor a parseable webpage date")
            event_date = date_parser.parse(date_node.get_text(" ", strip=True)).date()
            if not time_text or "all day" in time_text.casefold():
                return event_date, event_date + timedelta(days=1)
            start_text = re.split(r"\s+-\s+", time_text, maxsplit=1)[0]
            start_time = date_parser.parse(
                start_text, default=datetime.combine(event_date, time.min)
            ).time()
            start = datetime.combine(event_date, start_time, tzinfo=EASTERN)

        duration = str(data.get("duration", ""))
        duration_match = re.search(r"([0-9.]+)\s*hours?", duration, re.IGNORECASE)
        if duration_match:
            return start, start + timedelta(hours=float(duration_match.group(1)))
        pieces = re.split(r"\s+-\s+", time_text, maxsplit=1)
        if len(pieces) == 2:
            end_time = date_parser.parse(
                pieces[1], default=datetime.combine(start.date(), time.min)
            ).time()
            end = datetime.combine(start.date(), end_time, tzinfo=EASTERN)
            if end <= start:
                end += timedelta(days=1)
            return start, end
        return start, start + timedelta(hours=1)


def event_id_from_url(url: str) -> str | None:
    values = parse_qs(urlparse(urljoin(BASE_URL, url)).query).get("event")
    return values[0] if values else None
