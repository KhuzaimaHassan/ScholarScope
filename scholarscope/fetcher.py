"""Polite, robots-aware HTTP fetching with private, content-addressed snapshots."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Literal, Self
from urllib.robotparser import RobotFileParser

import httpx

FetchStatus = Literal["ok", "blocked", "not_found", "network_error"]
USER_AGENT = "ScholarScopeBot/0.1 (+https://github.com/KhuzaimaHassan/ScholarScope)"
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5


@dataclass(frozen=True)
class FetchResult:
    """One fetch outcome; cached results preserve their original UTC timestamp.

    HTTP metadata describes the last page response, never the robots response.
    If a redirect target is blocked before requesting it, final_url remains the
    redirecting page. Before any page response, it is the attempted page URL.
    """

    url: str
    status: FetchStatus
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    fetched_at: str | None = None
    content_sha256: str | None = None
    snapshot_path: Path | None = None
    content: bytes | None = None
    error: str | None = None
    from_cache: bool = False
    fetch_mode: Literal["http", "rendered"] = "http"
    playwright_version: str | None = None
    browser_version: str | None = None
    allow_hosts: tuple[str, ...] = ()
    blocked_requests: int = 0
    blocked_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RobotsPolicy:
    status: FetchStatus
    error: str | None = None
    parser: RobotFileParser | None = None


class Fetcher:
    """Fetch public URLs after robots checks and save private snapshots.

    URL and robots caches live only in this instance. Snapshots are addressed by
    content hash on disk, but a new instance/process refetches URLs.
    """

    def __init__(
        self,
        snapshot_dir: Path = Path("eval/snapshots/fetched"),
        *,
        user_agent: str = USER_AGENT,
        min_interval_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        max_bytes: int = 15_000_000,
    ) -> None:
        if max_bytes < 0:
            raise ValueError("max_bytes must be nonnegative")
        self.snapshot_dir = snapshot_dir
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            follow_redirects=False,
            timeout=timeout_seconds,
        )
        self._cache: dict[str, FetchResult] = {}
        self._robots_cache: dict[str, _RobotsPolicy] = {}
        self._last_request_by_host: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(self, url: str) -> FetchResult:
        """Fetch a URL, allowing at most five same-host, robots-permitted redirects."""

        if url in self._cache:
            return replace(self._cache[url], from_cache=True)

        result = FetchResult(url=url, status="network_error", fetched_at=self._utc_now())
        try:
            current = httpx.URL(url).copy_with(fragment=None)
        except (httpx.InvalidURL, ValueError) as exc:
            return self._remember(replace(result, error=f"Invalid URL: {exc}"))
        if current.scheme not in {"http", "https"} or not current.host:
            return self._remember(replace(result, error="URL must use HTTP or HTTPS"))

        result = replace(result, final_url=str(current))
        visited = {str(current)}
        redirects = 0
        while True:
            robots_status, robots_error = self._robots_allows(current)
            if robots_status != "ok":
                return self._remember(
                    replace(result, status=robots_status, error=f"{robots_error}: {current}")
                )

            self._wait_for_host(current.netloc.decode("ascii"))
            result = replace(
                result,
                final_url=str(current),
                http_status=None,
                content_type=None,
                fetched_at=self._utc_now(),
            )
            try:
                with self._client.stream("GET", current) as response:
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    result = replace(
                        result,
                        http_status=response.status_code,
                        content_type=content_type.strip().lower() or None,
                        fetched_at=self._utc_now(),
                    )
                    if response.status_code in REDIRECT_STATUSES:
                        target, error = self._redirect_target(current, response, redirects, visited)
                        if target is None:
                            return self._remember(replace(result, status="blocked", error=error))
                        current = target
                        visited.add(str(current))
                        redirects += 1
                        continue

                    if response.status_code == 404:
                        return self._remember(
                            replace(result, status="not_found", error="HTTP status 404")
                        )
                    if response.status_code in {401, 403}:
                        return self._remember(
                            replace(
                                result,
                                status="blocked",
                                error=f"HTTP status {response.status_code}",
                            )
                        )
                    if not response.is_success:
                        return self._remember(
                            replace(result, error=f"HTTP status {response.status_code}")
                        )

                    content = self._read_content(response)
                    if content is None:
                        return self._remember(replace(result, error="response too large"))
            except httpx.RequestError as exc:
                return self._remember(replace(result, error=f"HTTP request failed: {exc}"))

            digest = hashlib.sha256(content).hexdigest()
            extension = {"text/html": "html", "application/pdf": "pdf"}.get(
                result.content_type or "", "bin"
            )
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = self.snapshot_dir / f"{digest}.{extension}"
            if not snapshot_path.exists():
                snapshot_path.write_bytes(content)
            return self._remember(
                replace(
                    result,
                    status="ok",
                    content_sha256=digest,
                    snapshot_path=snapshot_path,
                    content=content,
                )
            )

    @staticmethod
    def _redirect_target(
        current: httpx.URL,
        response: httpx.Response,
        redirects: int,
        visited: set[str],
    ) -> tuple[httpx.URL | None, str | None]:
        if redirects >= MAX_REDIRECTS:
            return None, f"redirect hop limit exceeded (maximum {MAX_REDIRECTS})"
        location = response.headers.get("location")
        if not location:
            return None, "redirect missing Location header"
        try:
            target = current.join(location).copy_with(fragment=None)
        except (httpx.InvalidURL, ValueError) as exc:
            return None, f"invalid redirect target: {exc}"
        if target.scheme not in {"http", "https"} or not target.host:
            return None, "redirect target must use HTTP or HTTPS"
        if target.host != current.host:
            return None, f"redirect changes host from {current.host} to {target.host}"
        if str(target) in visited:
            return None, f"redirect loop detected: {target}"
        return target, None

    def _read_content(self, response: httpx.Response) -> bytes | None:
        content = bytearray()
        for chunk in response.iter_bytes(chunk_size=min(65_536, self.max_bytes + 1)):
            if len(content) + len(chunk) > self.max_bytes:
                return None
            content.extend(chunk)
        return bytes(content)

    def _remember(self, result: FetchResult) -> FetchResult:
        self._cache[result.url] = result
        return result

    def _robots_allows(self, url: httpx.URL) -> tuple[FetchStatus, str | None]:
        origin = str(url.copy_with(path="/", query=None, fragment=None))
        if origin not in self._robots_cache:
            self._robots_cache[origin] = self._load_robots(url)
        return self._robots_decision(url)

    def _robots_decision(self, url: httpx.URL) -> tuple[FetchStatus, str | None]:
        origin = str(url.copy_with(path="/", query=None, fragment=None))
        policy = self._robots_cache[origin]
        if policy.parser is not None and not policy.parser.can_fetch(self.user_agent, str(url)):
            return "blocked", "disallowed by robots.txt"
        return policy.status, policy.error

    async def check_robots_async(self, url: httpx.URL) -> tuple[FetchStatus, str | None]:
        """Renderer I/O bridge using the HTTP fetcher's SAME cache/status/policy rules.

        Async transport lets the renderer's overall deadline cancel robots I/O.
        No page or snapshot is fetched/written here. Call serially per instance.
        """
        origin = str(url.copy_with(path="/", query=None, fragment=None))
        if origin not in self._robots_cache:
            robots_url = url.copy_with(path="/robots.txt", query=None, fragment=None)
            await self.wait_for_host_async(url)
            try:
                async with (
                    httpx.AsyncClient(
                        headers={"User-Agent": self.user_agent},
                        follow_redirects=False,
                        timeout=self.timeout_seconds,
                        trust_env=False,
                    ) as client,
                    client.stream("GET", robots_url) as response,
                ):
                    status, error = self._classify_robots_status(response.status_code)
                    if status != "ok":
                        policy = _RobotsPolicy(status, error)
                    elif response.status_code in {404, 410}:
                        policy = _RobotsPolicy("ok")
                    elif not response.is_success:
                        policy = _RobotsPolicy(
                            "blocked",
                            f"robots.txt redirect not followed: HTTP status {response.status_code}",
                        )
                    else:
                        body = bytearray()
                        async for chunk in response.aiter_bytes(
                            chunk_size=min(65_536, self.max_bytes + 1)
                        ):
                            body.extend(chunk)
                            if len(body) > self.max_bytes:
                                break
                        if len(body) > self.max_bytes:
                            policy = _RobotsPolicy("network_error", "robots.txt response too large")
                        else:
                            parser = RobotFileParser(str(robots_url))
                            parser.parse(body.decode("utf-8", errors="replace").splitlines())
                            policy = _RobotsPolicy("ok", parser=parser)
            except httpx.RequestError as exc:
                policy = _RobotsPolicy(
                    "network_error", f"robots.txt network error: {type(exc).__name__}"
                )
            self._robots_cache[origin] = policy
        return self._robots_decision(url)

    async def wait_for_host_async(self, url: httpx.URL) -> None:
        """Renderer pacing, also honoring explicit robots crawl-delay."""
        origin = str(url.copy_with(path="/", query=None, fragment=None))
        policy = self._robots_cache.get(origin)
        delay = policy.parser.crawl_delay(self.user_agent) if policy and policy.parser else None
        interval = max(self.min_interval_seconds, delay if isinstance(delay, int) else 0)
        host = url.netloc.decode("ascii")
        remaining = interval - (monotonic() - self._last_request_by_host.get(host, 0))
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._last_request_by_host[host] = monotonic()

    def _load_robots(self, url: httpx.URL) -> _RobotsPolicy:
        robots_url = url.copy_with(path="/robots.txt", query=None, fragment=None)
        self._wait_for_host(url.netloc.decode("ascii"))
        try:
            with self._client.stream("GET", robots_url) as response:
                status, error = self._classify_robots_status(response.status_code)
                if status != "ok":
                    return _RobotsPolicy(status, error)
                if response.status_code in {404, 410}:
                    return _RobotsPolicy("ok")
                if not response.is_success:
                    return _RobotsPolicy(
                        "blocked",
                        f"robots.txt redirect not followed: HTTP status {response.status_code}",
                    )
                body = self._read_content(response)
                if body is None:
                    return _RobotsPolicy("network_error", "robots.txt response too large")
        except httpx.RequestError as exc:
            return _RobotsPolicy("network_error", f"robots.txt network error: {type(exc).__name__}")

        parser = RobotFileParser(str(robots_url))
        parser.parse(body.decode("utf-8", errors="replace").splitlines())
        return _RobotsPolicy("ok", parser=parser)

    @staticmethod
    def _classify_robots_status(status_code: int) -> tuple[FetchStatus, str | None]:
        if status_code in {404, 410}:
            return "ok", None
        if status_code in {401, 403}:
            return "blocked", f"robots.txt access denied: HTTP status {status_code}"
        if status_code >= 400:
            return "network_error", f"robots.txt HTTP status {status_code}"
        return "ok", None

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat()

    def _wait_for_host(self, host: str) -> None:
        elapsed = monotonic() - self._last_request_by_host.get(host, 0.0)
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            sleep(remaining)
        self._last_request_by_host[host] = monotonic()
