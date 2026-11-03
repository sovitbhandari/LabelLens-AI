"""Official DailyMed API client with retries and rate limiting."""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class DailyMedError(Exception):
    """Raised when DailyMed returns an unexpected or failed response."""


class DailyMedRateLimitError(DailyMedError):
    """Raised on HTTP 429."""


@dataclass(frozen=True)
class SplSearchHit:
    set_id: str
    title: str
    spl_version: int
    published_date: date | None


@dataclass(frozen=True)
class SplHistoryEntry:
    spl_version: int
    published_date: date | None


@dataclass(frozen=True)
class SplDocument:
    set_id: str
    spl_version: int
    xml_bytes: bytes
    source_url: str


def parse_dailymed_date(value: str | None) -> date | None:
    if not value or value in {"null", "None"}:
        return None
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    logger.warning("unparsed_dailymed_date", value=value)
    return None


class DailyMedClient:
    """Thin client over DailyMed REST v2 + historical ZIP download."""

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(self.settings.dailymed_timeout_seconds),
            headers={"User-Agent": "LabelLensAI/0.1 (portfolio research; respectful crawler)"},
            follow_redirects=True,
        )
        self._min_interval = 1.0 / max(self.settings.dailymed_rate_limit_rps, 0.1)
        self._last_request_at = 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> DailyMedClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, DailyMedRateLimitError)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        self._throttle()
        response = self._client.get(url, **kwargs)
        self._last_request_at = time.monotonic()
        if response.status_code == 429:
            raise DailyMedRateLimitError(f"Rate limited: {url}")
        if response.status_code >= 500:
            raise httpx.TransportError(f"DailyMed server error {response.status_code}")
        return response

    def search_spls(
        self, drug_name: str, *, page: int = 1, pagesize: int = 25
    ) -> list[SplSearchHit]:
        url = f"{self.settings.dailymed_base_url}/spls.json"
        response = self._get(
            url, params={"drug_name": drug_name, "page": page, "pagesize": pagesize}
        )
        if response.status_code != 200:
            raise DailyMedError(f"search_spls failed: {response.status_code}")
        payload = response.json()
        hits: list[SplSearchHit] = []
        for row in payload.get("data", []):
            hits.append(
                SplSearchHit(
                    set_id=row["setid"],
                    title=row.get("title") or "",
                    spl_version=int(row["spl_version"]),
                    published_date=parse_dailymed_date(row.get("published_date")),
                )
            )
        return hits

    def get_history(self, set_id: str) -> list[SplHistoryEntry]:
        url = f"{self.settings.dailymed_base_url}/spls/{set_id}/history.json"
        response = self._get(url)
        if response.status_code != 200:
            raise DailyMedError(f"get_history failed for {set_id}: {response.status_code}")
        payload = response.json()
        data = payload.get("data") or {}
        history = data.get("history") or []
        return [
            SplHistoryEntry(
                spl_version=int(entry["spl_version"]),
                published_date=parse_dailymed_date(entry.get("published_date")),
            )
            for entry in history
        ]

    def get_current_xml(self, set_id: str) -> SplDocument:
        url = f"{self.settings.dailymed_base_url}/spls/{set_id}.xml"
        response = self._get(url)
        if response.status_code != 200 or not response.content:
            raise DailyMedError(f"get_current_xml failed for {set_id}: {response.status_code}")
        # Version is inside XML; temporary 0 until parser fills it — caller should parse.
        return SplDocument(set_id=set_id, spl_version=0, xml_bytes=response.content, source_url=url)

    def get_version_xml(self, set_id: str, spl_version: int) -> SplDocument:
        """Fetch a specific historical version via ZIP download."""
        url = (
            f"{self.settings.dailymed_download_base_url}/getFile.cfm"
            f"?type=zip&setid={set_id}&version={spl_version}"
        )
        response = self._get(url)
        if response.status_code != 200 or not response.content:
            raise DailyMedError(
                f"get_version_xml failed for {set_id} v{spl_version}: {response.status_code}"
            )
        xml_bytes = self._extract_xml_from_zip(response.content)
        return SplDocument(
            set_id=set_id,
            spl_version=spl_version,
            xml_bytes=xml_bytes,
            source_url=url,
        )

    @staticmethod
    def _extract_xml_from_zip(zip_bytes: bytes) -> bytes:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                raise DailyMedError("ZIP archive contained no XML SPL document")
            # Prefer root-level XML
            xml_names.sort(key=lambda n: (n.count("/"), len(n)))
            return zf.read(xml_names[0])
