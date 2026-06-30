from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from free_food_dartmouth.http import HttpClient, SourceFetchError
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import EASTERN, clean_html, unique

BASE_URL = "https://geiselmed.dartmouth.edu/calendar/"
INDEX_URL = urljoin(BASE_URL, "index.php")
DETAIL_URL = urljoin(BASE_URL, "event_view.php")


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
        if failures:
            raise SourceFetchError(
                f"Geisel detail scan incomplete ({len(failures)} failures): "
                + "; ".join(failures[:3])
            )
        return SourceScan("Geisel", tuple(events))

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
