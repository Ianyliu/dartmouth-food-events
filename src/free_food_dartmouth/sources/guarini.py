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

BASE_URL = "https://guarinigrad.dartmouth.edu"
EVENTS_URL = f"{BASE_URL}/events/"
EVENT_PATH = re.compile(r"/events/(\d{4})/(\d{2})/(\d{2})/[^/?#]+/?$")
EVENT_ID = re.compile(r"event-(\d+)")
METADATA_LABELS = {"audience", "registration", "mode", "sponsor"}


class GuariniSource:
    def __init__(self, client: HttpClient | None = None, workers: int = 6) -> None:
        self.client = client or HttpClient()
        self.workers = workers

    def scan(self, start: date, end: date) -> SourceScan:
        urls = self._event_urls(start, end)
        events: list[EventRecord] = []
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {executor.submit(self._event, url): url for url in urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    event = future.result()
                    if start <= event.start_date < end:
                        events.append(event)
                except Exception as exc:
                    failures.append(f"{url}: {exc}")
        return SourceScan(
            "Guarini",
            tuple(events),
            complete=not failures,
            errors=tuple(failures),
        )

    def _event_urls(self, start: date, end: date) -> list[str]:
        urls: list[str] = []
        month = start.replace(day=1)
        while month < end:
            response = self.client.get(f"{EVENTS_URL}{month.year:04d}/{month.month:02d}/")
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select("#events-list li.event_item > a[href]"):
                url = urljoin(BASE_URL, str(anchor.get("href", "")))
                event_date = self._date_from_url(url)
                if event_date is not None and start <= event_date < end:
                    urls.append(url)
            month = (
                date(month.year + 1, 1, 1)
                if month.month == 12
                else date(month.year, month.month + 1, 1)
            )
        return list(dict.fromkeys(urls))

    def _event(self, url: str) -> EventRecord:
        response = self.client.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        event_root = soup.select_one("div.post.type-event[id]")
        heading = soup.select_one("h1.entry-title")
        if event_root is None or heading is None:
            raise ValueError("missing event detail structure")
        id_match = EVENT_ID.fullmatch(str(event_root.get("id", "")))
        if id_match is None:
            raise ValueError("missing stable event ID")

        title = heading.get_text(" ", strip=True)
        event_date = date_parser.parse(self._metadata(soup, "Date", required=True)).date()
        start, end = self._date_times(event_date, self._metadata(soup, "Time"))
        location = self._metadata(soup, "Location")

        content = soup.select_one(".entry-content")
        audience = self._labeled_value(content, "Audience")
        sponsor = self._labeled_value(content, "Sponsor")
        description = self._description(content)
        summary_meta = soup.select_one('meta[property="og:description"]')
        summary = (
            clean_html(str(summary_meta.get("content", "")))
            if summary_meta is not None
            else description[:500]
        )

        urls = [url]
        for anchor in soup.select(".entry-meta a[href], .entry-content a[href], #rsvp-cta a[href]"):
            href = urljoin(BASE_URL, str(anchor.get("href", "")))
            if href.startswith(("http://", "https://")):
                urls.append(href)
        categories = unique(
            [
                anchor.get_text(" ", strip=True)
                for anchor in soup.select(
                    ".event-tags a, .post-tags a, .entry-utility a[rel='tag']"
                )
            ]
        )
        source_key = f"guarini:{id_match.group(1)}"
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=summary,
            location=location,
            sponsor=sponsor,
            audience=audience,
            urls=unique(urls),
            categories=categories,
            source_keys=(source_key,),
            sources=("Guarini",),
            uid_key=source_key,
        )

    @staticmethod
    def _date_from_url(url: str) -> date | None:
        match = EVENT_PATH.search(url)
        if match is None:
            return None
        return date(*(int(value) for value in match.groups()))

    @staticmethod
    def _metadata(soup: BeautifulSoup, label: str, *, required: bool = False) -> str:
        for item in soup.select(".entry-meta-item"):
            label_node = item.select_one(".screen-reader-text")
            if label_node is None:
                continue
            found_label = label_node.get_text(" ", strip=True).rstrip(":")
            if found_label.casefold() != label.casefold():
                continue
            copy = BeautifulSoup(str(item), "html.parser")
            for node in copy.select(".screen-reader-text, .icon"):
                node.decompose()
            return clean_html(str(copy))
        if required:
            raise ValueError(f"missing event {label.casefold()}")
        return ""

    @staticmethod
    def _date_times(event_date: date, time_text: str) -> tuple[date | datetime, date | datetime]:
        if not time_text or "all day" in time_text.casefold():
            return event_date, event_date + timedelta(days=1)
        pieces = re.split(r"\s+(?:-|\u2013|\u2014|to)\s+", time_text, maxsplit=1)
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
    def _labeled_value(content: Tag | None, label: str) -> str:
        if content is None:
            return ""
        lines = clean_html(str(content)).splitlines()
        target = label.casefold()
        for index, line in enumerate(lines):
            before, separator, after = line.partition(":")
            if before.strip().casefold() != target:
                continue
            if separator and after.strip():
                return after.strip()
            if index + 1 < len(lines):
                return lines[index + 1].strip()
        return ""

    @staticmethod
    def _description(content: Tag | None) -> str:
        if content is None:
            return ""
        copy = BeautifulSoup(str(content), "html.parser")
        for node in copy.select(".more-info-box, script, style"):
            node.decompose()
        for paragraph in copy.find_all("p"):
            labels = {
                strong.get_text(" ", strip=True).rstrip(":").casefold()
                for strong in paragraph.find_all("strong")
            }
            if labels & METADATA_LABELS:
                paragraph.decompose()
        return clean_html(str(copy))
