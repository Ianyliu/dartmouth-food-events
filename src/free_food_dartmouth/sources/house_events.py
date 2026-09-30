from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, clean_html, easternize, unique


@dataclass(frozen=True, slots=True)
class HouseEventListConfig:
    name: str
    base_url: str
    events_url: str
    key_prefix: str


SCHOOL_HOUSE = HouseEventListConfig(
    name="School House",
    base_url="https://schoolhouse.dartmouth.edu",
    events_url="https://schoolhouse.dartmouth.edu/new-events",
    key_prefix="school-house",
)
NORTH_PARK = HouseEventListConfig(
    name="North Park House",
    base_url="https://www.northpark.dartmouth.edu",
    events_url="https://www.northpark.dartmouth.edu/house-events",
    key_prefix="north-park-house",
)

DATE_TEXT = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"\d{1,2},\s+\d{4}",
    re.IGNORECASE,
)


class HouseEventListSource:
    def __init__(
        self,
        config: HouseEventListConfig,
        client: HttpClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or HttpClient()

    def scan(self, start: date, end: date) -> SourceScan:
        response = self.client.get(self.config.events_url)
        soup = BeautifulSoup(response.text, "html.parser")
        blocks = soup.select(".eventlist-event")
        if not blocks:
            raise ValueError(f"missing {self.config.name} event-list structure")

        events: list[EventRecord] = []
        failures: list[str] = []
        for block in blocks:
            try:
                event_date = self._event_date(block)
                if not start <= event_date < end:
                    continue
                events.append(self._event(block))
            except Exception as exc:
                title = self._title(block) or "unknown event"
                failures.append(f"{title}: {exc}")
        return SourceScan(
            self.config.name,
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    def _event(self, block: Tag) -> EventRecord:
        title_link = block.select_one(
            "a.eventlist-title-link[href], .eventlist-title a[href], "
            "h1 a[href], h2 a[href], h3 a[href]"
        )
        if title_link is None:
            raise ValueError("missing event title link")
        title = self._title(block)
        if not title:
            raise ValueError("missing event title")

        detail_url = urljoin(self.config.base_url, str(title_link.get("href", "")))
        slug = urlparse(detail_url).path.rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            raise ValueError("missing event slug")

        event_date = self._event_date(block)
        start, end = self._date_times(block, event_date)
        location_node = block.select_one(
            ".eventlist-meta-address, .eventlist-meta-location, .event-location"
        )
        location = clean_html(str(location_node)) if location_node is not None else ""

        description_node = block.select_one(".eventlist-description, .eventlist-excerpt")
        description = clean_html(str(description_node)) if description_node is not None else ""
        urls = [detail_url]
        if description_node is not None:
            for anchor in description_node.select("a[href]"):
                href = urljoin(self.config.base_url, str(anchor.get("href", "")))
                if href.startswith(("http://", "https://")):
                    urls.append(href)

        source_key = f"{self.config.key_prefix}:{slug}"
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=description.split("\n", 1)[0][:500],
            location=location,
            sponsor=self.config.name,
            urls=unique(urls),
            categories=("House Community", self.config.name),
            source_keys=(source_key,),
            sources=(self.config.name,),
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
        cls,
        block: Tag,
        event_date: date,
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
        parsed = date_parser.parse(text, fuzzy=True)
        start = datetime.combine(event_date, parsed.time(), tzinfo=EASTERN)
        return start, start + timedelta(hours=1)

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
        default = datetime.combine(event_date, time.min)
        parsed_time = date_parser.parse(text, default=default).time()
        return datetime.combine(event_date, parsed_time, tzinfo=EASTERN)


def school_house_source(client: HttpClient | None = None) -> HouseEventListSource:
    return HouseEventListSource(SCHOOL_HOUSE, client)


def north_park_source(client: HttpClient | None = None) -> HouseEventListSource:
    return HouseEventListSource(NORTH_PARK, client)
