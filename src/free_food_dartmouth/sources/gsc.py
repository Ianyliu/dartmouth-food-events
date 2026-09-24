from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, clean_html, easternize, unique

BASE_URL = "https://gsc.dartmouth.edu"
EVENTS_URL = f"{BASE_URL}/events-list"
EVENT_PATH = re.compile(r"^/events-list/([^/?#]+)/?$")
TIME_RANGE = re.compile(r"\s+(?:-|\u2013|\u2014|to)\s+", re.IGNORECASE)
DATE_TEXT = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"\d{1,2},\s+\d{4}",
    re.IGNORECASE,
)


class GscSource:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def scan(self, start: date, end: date) -> SourceScan:
        response = self.client.get(EVENTS_URL)
        soup = BeautifulSoup(response.text, "html.parser")
        blocks = soup.select(".eventlist-event")
        if not blocks:
            raise ValueError("missing GSC event-list structure")

        events: list[EventRecord] = []
        failures: list[str] = []
        for block in blocks:
            try:
                event = self._event(block)
                if start <= event.start_date < end:
                    events.append(event)
            except Exception as exc:
                title = self._title(block) or "unknown event"
                failures.append(f"{title}: {exc}")
        return SourceScan(
            "Dartmouth GSC",
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    @classmethod
    def _event(cls, block: Tag) -> EventRecord:
        title_link = block.select_one(
            "a.eventlist-title-link[href], .eventlist-title a[href], "
            "h1 a[href], h2 a[href], h3 a[href]"
        )
        if title_link is None:
            raise ValueError("missing event title link")
        title = cls._title(block)
        if not title:
            raise ValueError("missing event title")

        detail_url = urljoin(BASE_URL, str(title_link.get("href", "")))
        match = EVENT_PATH.fullmatch(urlparse(detail_url).path)
        if match is None:
            raise ValueError("unexpected event detail URL")

        event_date = cls._event_date(block)
        start, end = cls._date_times(block, event_date)
        location_node = block.select_one(
            ".eventlist-meta-address, .eventlist-meta-location, .event-location"
        )
        location = clean_html(str(location_node)) if location_node is not None else ""

        description_node = block.select_one(".eventlist-description, .eventlist-excerpt")
        description = clean_html(str(description_node)) if description_node is not None else ""
        urls = [detail_url]
        if description_node is not None:
            for anchor in description_node.select("a[href]"):
                href = urljoin(BASE_URL, str(anchor.get("href", "")))
                if href.startswith(("http://", "https://")):
                    urls.append(href)

        source_key = f"gsc:{match.group(1)}"
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=description.split("\n", 1)[0][:500],
            location=location,
            urls=unique(urls),
            categories=("GSC",),
            source_keys=(source_key,),
            sources=("Dartmouth GSC",),
            uid_key=source_key,
        )

    @staticmethod
    def _title(block: Tag) -> str:
        node = block.select_one(".eventlist-title")
        if node is None:
            node = block.select_one("a.eventlist-title-link, h1, h2, h3")
        return node.get_text(" ", strip=True) if node is not None else ""

    @staticmethod
    def _event_date(block: Tag) -> date:
        node = block.select_one("time.event-date, .eventlist-meta-date time, .eventlist-meta-date")
        if node is None:
            raise ValueError("missing event date")
        raw = str(node.get("datetime", "")).strip()
        if raw:
            return date_parser.isoparse(raw).date()
        text = node.get_text(" ", strip=True)
        if not text:
            raise ValueError("missing event date")
        date_match = DATE_TEXT.search(text)
        if date_match is not None:
            return date_parser.parse(date_match.group(0), fuzzy=True).date()
        return date_parser.parse(text, fuzzy=True).date()

    @classmethod
    def _date_times(
        cls, block: Tag, event_date: date
    ) -> tuple[date | datetime, date | datetime]:
        start_node = block.select_one(".event-time-localized-start")
        end_node = block.select_one(".event-time-localized-end")
        if start_node is not None:
            start = cls._datetime_from_node(start_node, event_date)
            end = (
                cls._datetime_from_node(end_node, event_date)
                if end_node is not None
                else start + timedelta(hours=1)
            )
            if end <= start:
                end += timedelta(days=1)
            return start, end

        time_node = block.select_one(".eventlist-meta-time, .event-time-localized")
        if time_node is None:
            return event_date, event_date + timedelta(days=1)
        text = time_node.get_text(" ", strip=True)
        if not text or "all day" in text.casefold():
            return event_date, event_date + timedelta(days=1)
        pieces = TIME_RANGE.split(text, maxsplit=1)
        default = datetime.combine(event_date, time.min)
        start_time = date_parser.parse(pieces[0], default=default).time()
        end_time = (
            date_parser.parse(pieces[1], default=default).time()
            if len(pieces) == 2
            else (datetime.combine(event_date, start_time) + timedelta(hours=1)).time()
        )
        start = datetime.combine(event_date, start_time, tzinfo=EASTERN)
        end = datetime.combine(event_date, end_time, tzinfo=EASTERN)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    @staticmethod
    def _datetime_from_node(node: Tag, event_date: date) -> datetime:
        raw = str(node.get("datetime", "")).strip()
        if raw and "T" in raw:
            parsed = easternize(date_parser.isoparse(raw))
            if isinstance(parsed, datetime):
                return parsed
        text = node.get_text(" ", strip=True)
        if not text:
            raise ValueError("missing event time")
        parsed_time = date_parser.parse(
            text, default=datetime.combine(event_date, time.min)
        ).time()
        return datetime.combine(event_date, parsed_time, tzinfo=EASTERN)
