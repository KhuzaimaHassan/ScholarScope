"""Polite, robots-aware HTTP fetching with content-addressed snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from time import monotonic, sleep
from typing import Literal, Self
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

FetchStatus = Literal["ok", "blocked", "not_found", "network_error"]
USER_AGENT = "ScholarScopeBot/0.1 (+https://github.com/KhuzaimaHassan/ScholarScope)"


@dataclass(frozen=True)
class FetchResult:
    """The outcome and metadata of one fetch attempt."""

    url: str
    status: FetchStatus
    content_sha256: str | None = None
    snapshot_path: Path | None = None
    content: bytes | None = None
    error: str | None = None
    from_cache: bool = False


class Fetcher:
    """Fetch public URLs after a robots check and save private snapshots."""

    def __init__(
        self,
        snapshot_dir: Path = Path("eval/snapshots"),
        *,
        user_agent: str = USER_AGENT,
        min_interval_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.snapshot_dir = snapshot_dir
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            timeout=timeout_seconds,
        )
        self._cache: dict[str, FetchResult] = {}
        self._robots_cache: dict[str, tuple[FetchStatus, str | None]] = {}
        self._last_request_by_host: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(self, url: str) -> FetchResult:
        """Fetch ``url`` or return its in-process cached result."""

        if url in self._cache:
            cached = self._cache[url]
            return FetchResult(
                url=cached.url,
                status=cached.status,
                content_sha256=cached.content_sha256,
                snapshot_path=cached.snapshot_path,
                content=cached.content,
                error=cached.error,
                from_cache=True,
            )

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return self._remember(
                FetchResult(url=url, status="network_error", error="URL must use HTTP or HTTPS")
            )

        robots_status, robots_error = self._robots_allows(url)
        if robots_status != "ok":
            return self._remember(
                FetchResult(url=url, status=robots_status, error=robots_error)
            )

        self._wait_for_host(parsed.netloc)
        try:
            response = self._client.get(url)
        except httpx.RequestError as exc:
            return self._remember(
                FetchResult(url=url, status="network_error", error=f"HTTP request failed: {exc}")
            )

        if response.status_code == 404:
            return self._remember(
                FetchResult(url=url, status="not_found", error="HTTP status 404")
            )
        if response.status_code in {401, 403}:
            return self._remember(
                FetchResult(url=url, status="blocked", error=f"HTTP status {response.status_code}")
            )
        if response.is_error:
            return self._remember(
                FetchResult(url=url, status="network_error", error=f"HTTP status {response.status_code}")
            )

        content = response.content
        digest = hashlib.sha256(content).hexdigest()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshot_dir / f"{digest}.bin"
        if not snapshot_path.exists():
            snapshot_path.write_bytes(content)
        return self._remember(
            FetchResult(
                url=url,
                status="ok",
                content_sha256=digest,
                snapshot_path=snapshot_path,
                content=content,
            )
        )

    def _remember(self, result: FetchResult) -> FetchResult:
        self._cache[result.url] = result
        return result

    def _robots_allows(self, url: str) -> tuple[FetchStatus, str | None]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots_cache:
            return self._robots_cache[origin]

        robots_url = urljoin(f"{origin}/", "robots.txt")
        self._wait_for_host(parsed.netloc)
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self._client.get(robots_url)
        except httpx.RequestError as exc:
            result: tuple[FetchStatus, str | None] = (
                "network_error",
                f"robots.txt network error: {type(exc).__name__}",
            )
            self._robots_cache[origin] = result
            return result

        if response.status_code >= 400:
            result = self._classify_robots_status(robots_url, response.status_code)
            if result[0] != "ok":
                self._robots_cache[origin] = result
                return result
            parser.parse([])
        else:
            parser.parse(response.text.splitlines())

        allowed = parser.can_fetch(self.user_agent, url)
        result = ("ok", None) if allowed else ("blocked", "disallowed by robots.txt")
        self._robots_cache[origin] = result
        return result

    @staticmethod
    def _classify_robots_status(url: str, status_code: int) -> tuple[FetchStatus, str | None]:
        """Classify an HTTP robots response, preserving HTTPError ordering."""

        try:
            raise HTTPError(url, status_code, f"robots.txt HTTP status {status_code}", Message(), None)
        except HTTPError as exc:
            if exc.code in {404, 410}:
                return "ok", None
            if exc.code in {401, 403}:
                return "blocked", f"robots.txt access denied: HTTP status {exc.code}"
            return "network_error", f"robots.txt HTTP status {exc.code}"
        except OSError as exc:
            return "network_error", f"robots.txt network error: {type(exc).__name__}"

    def _wait_for_host(self, host: str) -> None:
        elapsed = monotonic() - self._last_request_by_host.get(host, 0.0)
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            sleep(remaining)
        self._last_request_by_host[host] = monotonic()
