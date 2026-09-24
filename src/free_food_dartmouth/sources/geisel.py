from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from free_food_dartmouth.http import HttpClient
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, clean_html, unique

BASE_URL = "https://geiselmed.dartmouth.edu/calendar/"
INDEX_URL = urljoin(BASE_URL, "index.php")
DETAIL_URL = urljoin(BASE_URL, "event_view.php")
DICE_URL = "https://geiselmed.dartmouth.edu/dice/dice-events/"

DICE_DATE_LINE = re.compile(
    r"^(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December)\s+\d{1,2},\s+\d{4}\s*\|",
    re.IGNORECASE,
)
MERIDIEM = re.compile(r"\b([ap])\.?m\.?\b", re.IGNORECASE)
TIME_RANGE = re.compile(r"\s*[-\u2013\u2014]\s*")


class GeiselDiceSource:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def scan(self, start: date, end: date) -> SourceScan:
        response = self.client.get(DICE_URL)
        soup = BeautifulSoup(response.text, "html.parser")
        events, failures = self._events(soup)
        selected = tuple(event for event in events if start <= event.start_date < end)
        return SourceScan(
            "Geisel DICE",
            selected,
            complete=not failures,
            errors=tuple(failures),
        )

    def _events(self, soup: BeautifulSoup) -> tuple[list[EventRecord], list[str]]:
        blocks = self._blocks(soup)
        date_indices = [
            index
            for index, block in enumerate(blocks)
            if DICE_DATE_LINE.match(block.get_text(" ", strip=True))
        ]
        events: list[EventRecord] = []
        failures: list[str] = []
        for position, date_index in enumerate(date_indices):
            title_index = self._title_index(blocks, date_index)
            if title_index is None:
                failures.append(f"block {date_index}: missing event title")
                continue
            next_title_index = len(blocks)
            if position + 1 < len(date_indices):
                candidate = self._title_index(blocks, date_indices[position + 1])
                if candidate is not None:
                    next_title_index = candidate
            try:
                events.append(
                    self._event_from_blocks(
                        blocks,
                        title_index,
                        date_index,
                        next_title_index,
                    )
                )
            except Exception as exc:
                title = blocks[title_index].get_text(" ", strip=True)
                failures.append(f"{title}: {exc}")
        return events, failures

    @staticmethod
    def _blocks(soup: BeautifulSoup) -> list[Tag]:
        root = soup.select_one(".entry-content") or soup.select_one("main") or soup
        return [
            block
            for block in root.find_all(("h1", "h2", "h3", "h4", "h5", "h6", "p"))
            if isinstance(block, Tag)
        ]

    @staticmethod
    def _title_index(blocks: list[Tag], date_index: int) -> int | None:
        for index in range(date_index - 1, -1, -1):
            text = blocks[index].get_text(" ", strip=True)
            if not text:
                continue
            if DICE_DATE_LINE.match(text):
                return None
            if text.casefold() in {"upcoming events", "view past events"}:
                continue
            return index
        return None

    @classmethod
    def _event_from_blocks(
        cls,
        blocks: list[Tag],
        title_index: int,
        date_index: int,
        next_title_index: int,
    ) -> EventRecord:
        title = blocks[title_index].get_text(" ", strip=True)
        metadata = blocks[date_index].get_text(" ", strip=True)
        start, end, location = cls._date_time_location(metadata)

        description_parts: list[str] = []
        urls = [DICE_URL]
        for block in blocks[date_index + 1 : next_title_index]:
            text = block.get_text(" ", strip=True)
            if text.casefold() == "view past events":
                break
            if text:
                description_parts.append(text)
            for link in block.select("a[href]"):
                href = str(link.get("href", "")).strip()
                if href:
                    urls.append(urljoin(DICE_URL, href))
        description = "\n".join(description_parts)
        source_key = cls._source_key(title, start)
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=description.split("\n", 1)[0][:500],
            location=location,
            sponsor="DICE Office",
            urls=unique(urls),
            categories=("DICE",),
            source_keys=(source_key,),
            sources=("Geisel DICE",),
            uid_key=source_key,
        )

    @staticmethod
    def _source_key(title: str, start: date | datetime) -> str:
        event_date = start.date() if isinstance(start, datetime) else start
        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:80]
        return f"geisel-dice:{event_date.isoformat()}:{slug}"

    @classmethod
    def _date_time_location(cls, metadata: str) -> tuple[date | datetime, date | datetime, str]:
        parts = [part.strip() for part in metadata.split("|")]
        if len(parts) < 2:
            raise ValueError("missing date/time metadata")
        event_date = date_parser.parse(parts[0], fuzzy=False).date()
        location = ", ".join(part for part in parts[2:] if part)
        time_text = parts[1].strip()
        if not time_text or "all day" in time_text.casefold():
            return event_date, event_date + timedelta(days=1), location

        pieces = TIME_RANGE.split(time_text, maxsplit=1)
        if len(pieces) == 1:
            start_time = cls._parse_time(pieces[0], event_date)
            start = datetime.combine(event_date, start_time, tzinfo=EASTERN)
            return start, start + timedelta(hours=1), location

        start_piece, end_piece = pieces
        start_meridiem = MERIDIEM.search(start_piece)
        end_meridiem = MERIDIEM.search(end_piece)
        if start_meridiem is None and end_meridiem is not None:
            marker = end_meridiem.group(1).casefold()
            candidate_start = cls._parse_time(f"{start_piece} {marker}m", event_date)
            candidate_end = cls._parse_time(end_piece, event_date)
            if candidate_start >= candidate_end:
                marker = "a" if marker == "p" else "p"
            start_piece = f"{start_piece} {marker}m"
        elif end_meridiem is None and start_meridiem is not None:
            marker = start_meridiem.group(1).casefold()
            candidate_start = cls._parse_time(start_piece, event_date)
            candidate_end = cls._parse_time(f"{end_piece} {marker}m", event_date)
            if candidate_end <= candidate_start:
                marker = "a" if marker == "p" else "p"
            end_piece = f"{end_piece} {marker}m"

        start_time = cls._parse_time(start_piece, event_date)
        end_time = cls._parse_time(end_piece, event_date)
        start = datetime.combine(event_date, start_time, tzinfo=EASTERN)
        end = datetime.combine(event_date, end_time, tzinfo=EASTERN)
        if end <= start:
            end += timedelta(days=1)
        return start, end, location

    @staticmethod
    def _parse_time(value: str, event_date: date) -> time:
        normalized = value.strip().casefold()
        if normalized == "noon":
            return time(12)
        if normalized == "midnight":
            return time(0)
        default = datetime.combine(event_date, time.min)
        return date_parser.parse(value, default=default).time()


class GeiselSource:
    def __init__(self, client: HttpClient | None = None, workers: int = 6) -> None:
        self.client = client or HttpClient()
        self.workers = workers

    def scan(self, start: date, end: date) -> SourceScan:
        references = self._references(start, end)
        events: list[EventRecord] = []
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self._event, event_id, instance): (event_id, instance)
                for event_id, instance in references
            }
            for future in as_completed(futures):
                event_id, instance = futures[future]
                try:
                    event = future.result()
                    if start <= event.start_date < end:
                        events.append(event)
                except Exception as exc:
                    failures.append(f"{event_id}/{instance}: {exc}")
        return SourceScan(
            "Geisel",
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    def _references(self, start: date, end: date) -> list[tuple[str, str]]:
        offset_from_sunday = (start.weekday() + 1) % 7
        anchor = start - timedelta(days=offset_from_sunday)
        references: list[tuple[str, str]] = []
        while anchor < end:
            response = self.client.get(
                INDEX_URL,
                params={
                    "calendar": 1,
                    "v": "w",
                    "m": anchor.month,
                    "d": anchor.day,
                    "y": anchor.year,
                },
            )
            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.select('a[href*="event_view.php?eid="]'):
                href = str(link.get("href", ""))
                event_match = re.search(r"[?&]eid=(\d+)", href)
                instance_match = re.search(r"[?&]instance=(\d{4}-\d{1,2}-\d{1,2})", href)
                if event_match and instance_match:
                    references.append((event_match.group(1), instance_match.group(1)))
            anchor += timedelta(days=7)
        return list(dict.fromkeys(references))

    def _event(self, event_id: str, instance: str) -> EventRecord:
        detail_url = f"{DETAIL_URL}?eid={event_id}&instance={instance}"
        response = self.client.get(detail_url)
        soup = BeautifulSoup(response.text, "html.parser")
        heading = soup.select_one("#event h1")
        if heading is None:
            raise ValueError("missing event title")
        title = heading.get_text(" ", strip=True)
        rows = self._rows(soup)
        start, end = self._date_times(rows, instance)
        categories = self._categories(heading)
        original_url = detail_url
        urls = [original_url]
        external = rows.get("URL", "")
        if external.startswith(("http://", "https://")):
            urls.append(external)
        location = rows.get("Location", "")
        address = rows.get("Address", "")
        if address:
            location = f"{location}, {address}" if location else address
        description = rows.get("Notes", "")
        organizer = rows.get("Organizer", "")
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=description.split("\n", 1)[0][:500],
            location=location,
            sponsor=organizer,
            urls=unique(urls),
            categories=categories,
            source_keys=(f"geisel:{event_id}:{instance}",),
            sources=("Geisel",),
            uid_key=f"geisel:{event_id}:{instance}",
        )

    @staticmethod
    def _rows(soup: BeautifulSoup) -> dict[str, str]:
        rows: dict[str, str] = {}
        for row in soup.select("#event tr"):
            label = row.find("b")
            cells = row.find_all("td", recursive=False)
            if label is None or len(cells) < 2:
                continue
            key = label.get_text(" ", strip=True).rstrip(":")
            value_cell = cells[-1]
            for script in value_cell.find_all("script"):
                script.extract()
            value = clean_html(str(value_cell))
            if key and value:
                rows[key] = value
        return rows

    @staticmethod
    def _categories(heading: Tag) -> tuple[str, ...]:
        parent_text = heading.parent.get_text(" ", strip=True) if heading.parent else ""
        match = re.search(r"\(([^()]*)\)\s*$", parent_text)
        return unique(match.group(1).split(",")) if match else ()

    @staticmethod
    def _date_times(rows: dict[str, str], instance: str) -> tuple[date | datetime, date | datetime]:
        date_text = rows.get("Date", instance).split()[-1]
        event_date = date_parser.parse(date_text).date()
        time_text = rows.get("Time", "").strip()
        if not time_text or "all day" in time_text.casefold():
            return event_date, event_date + timedelta(days=1)
        pieces = re.split(r"\s+-\s+", time_text, maxsplit=1)
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
