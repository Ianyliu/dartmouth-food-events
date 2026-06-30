from __future__ import annotations

import time
from dataclasses import dataclass

import requests


class SourceFetchError(RuntimeError):
    """Raised when a source cannot be fetched completely."""


@dataclass(slots=True)
class HttpClient:
    timeout: float = 20.0
    attempts: int = 3
    user_agent: str = (
        "free-food-dartmouth/0.1 "
        "(+https://github.com/Ianyliu/dartmouth-food-events; calendar aggregator)"
    )

    def get(self, url: str, *, params: dict[str, str | int] | None = None) -> requests.Response:
        error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    headers={"User-Agent": self.user_agent, "Accept": "*/*"},
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                error = exc
                if attempt + 1 < self.attempts:
                    time.sleep(0.5 * (2**attempt))
        raise SourceFetchError(f"Failed to fetch {url}: {error}") from error
