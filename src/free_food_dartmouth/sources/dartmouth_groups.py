from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from free_food_dartmouth.http import HttpClient, SourceFetchError
from free_food_dartmouth.models import EventRecord, SourceScan
from free_food_dartmouth.utils import clean_html, easternize, unique

BASE_URL = "https://dartmouthgroups.dartmouth.edu"
LIST_URL = f"{BASE_URL}/mobile_ws/v17/mobile_events_list"
DETAIL_URL = f"{BASE_URL}/rsvp_boot"


class DartmouthGroupsSource:
    def __init__(
        self,
        client: HttpClient | None = None,
        workers: int = 6,
        page_size: int = 40,
    ) -> None:
        self.client = client or HttpClient()
        self.workers = workers
        self.page_size = page_size

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
                    if start <= event.start_date < end:
                        events.append(event)
                except Exception as exc:
                    failures.append(f"{event_id}: {exc}")
        if failures:
            raise SourceFetchError(
                f"Dartmouth Groups detail scan incomplete ({len(failures)} failures): "
                + "; ".join(failures[:3])
            )
        return SourceScan("Dartmouth Groups", tuple(events))

    def _event_ids(self, start: date, end: date) -> list[str]:
        offset = 0
        event_ids: list[str] = []
        while True:
            response = self.client.get(
                LIST_URL,
                params={
                    "range": offset,
                    "limit": self.page_size,
                    "filter8": start.strftime("%d %b %Y"),
                    "filter9": (end - timedelta(days=1)).strftime("%d %b %Y"),
                    "order": "",
                    "search_word": "",
                },
            )
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("event listing did not return a JSON list")
            page_ids: list[str] = []
            total = 0
            for item in payload:
                if not isinstance(item, dict):
                    continue
                total = max(total, self._integer(item.get("counter")))
                fields = self._fields(item)
                event_id = fields.get("eventId", "")
                if event_id:
                    page_ids.append(event_id)
            event_ids.extend(page_ids)
            offset += self.page_size
            if not page_ids or offset >= total:
                break
        return list(dict.fromkeys(event_ids))

    def _event(self, event_id: str) -> EventRecord:
        detail_url = f"{DETAIL_URL}?id={event_id}"
        response = self.client.get(detail_url)
        soup = BeautifulSoup(response.text, "html.parser")
        data = self._json_ld(soup)
        if not data:
            raise ValueError("missing event JSON-LD")

        start = self._date_value(data.get("startDate"))
        raw_end = data.get("endDate")
        if raw_end:
            end = self._date_value(raw_end)
        elif isinstance(start, datetime):
            end = start + timedelta(hours=1)
        else:
            end = start + timedelta(days=1)
        title = clean_html(str(data.get("name", "")))
        if not title:
            raise ValueError("missing event title")

        details = self._card(soup, "Details")
        description = self._description(details) or clean_html(str(data.get("description", "")))
        summary = clean_html(str(data.get("description", "")))
        location = self._location(data.get("location"))
        sponsor = self._sponsor(self._card(soup, "Hosted By"))
        categories = unique(
            [
                anchor.get_text(" ", strip=True)
                for anchor in soup.select(
                    'main a[href*="event_type="], main a[href*="topic_tags="]'
                )
            ]
        )
        urls = [detail_url]
        if details is not None:
            for anchor in details.select("a[href]"):
                href = urljoin(BASE_URL, str(anchor.get("href", "")))
                if href.startswith(("http://", "https://")) and "/upload/" not in href:
                    urls.append(href)
        return EventRecord(
            title=title,
            start=start,
            end=end,
            description=description,
            summary=summary,
            location=location,
            sponsor=sponsor,
            urls=unique(urls),
            categories=categories,
            source_keys=(f"dartmouth-groups:{event_id}",),
            sources=("Dartmouth Groups",),
            uid_key=f"dartmouth-groups:{event_id}",
        )

    @staticmethod
    def _fields(item: dict[str, Any]) -> dict[str, str]:
        names = [name for name in str(item.get("fields", "")).split(",") if name]
        return {
            name: str(item.get(f"p{index}", "") or "")
            for index, name in enumerate(names)
        }

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return int(str(value))
        except ValueError:
            return 0

    @staticmethod
    def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            if not isinstance(script, Tag) or not script.string:
                continue
            raw = script.string
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', "", raw))
            if isinstance(parsed, dict) and parsed.get("@type") == "Event":
                return parsed
        return {}

    @staticmethod
    def _date_value(value: object) -> date | datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError("missing event date")
        parsed = date_parser.isoparse(text)
        if len(text) <= 10:
            return parsed.date()
        return easternize(parsed)

    @staticmethod
    def _card(soup: BeautifulSoup, heading_text: str) -> Tag | None:
        for heading in soup.select("h2"):
            if heading.get_text(" ", strip=True) == heading_text:
                card = heading.find_parent("div", class_="card-block")
                return card if isinstance(card, Tag) else None
        return None

    @staticmethod
    def _description(card: Tag | None) -> str:
        if card is None:
            return ""
        copy = BeautifulSoup(str(card), "html.parser")
        for node in copy.select(".card-block__title, .text-center, button, script, style"):
            node.decompose()
        return clean_html(str(copy))

    @staticmethod
    def _location(value: object) -> str:
        if not isinstance(value, dict):
            return clean_html(str(value or ""))
        name = clean_html(str(value.get("name", "")))
        address = clean_html(str(value.get("address", "")))
        if address and address != name:
            return f"{name}, {address}" if name else address
        return name

    @staticmethod
    def _sponsor(card: Tag | None) -> str:
        if card is None:
            return ""
        host = card.find("strong")
        host_text = host.get_text(" ", strip=True) if host else ""
        text = card.get_text(" ", strip=True)
        cohost = ""
        if "Co-hosted with:" in text:
            cohost = (
                text.split("Co-hosted with:", 1)[1]
                .split("Contact the organizers", 1)[0]
                .strip()
            )
        return " / ".join(unique((host_text, cohost)))
