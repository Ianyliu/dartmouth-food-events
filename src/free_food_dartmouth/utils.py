from __future__ import annotations

import html
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

EASTERN = ZoneInfo("America/New_York")


def clean_html(value: str) -> str:
    soup = BeautifulSoup(html.unescape(value), "html.parser")
    text = soup.get_text("\n", strip=True)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def easternize(value: date | datetime) -> date | datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=EASTERN)
        return value.astimezone(EASTERN)
    return value


def unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))
