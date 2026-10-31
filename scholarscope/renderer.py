"""Optional, robots-aware browser fallback. No evasion or interactions.

Playwright is imported ONLY after robots permits navigation. Page HTML is
untrusted, private source data; never interpret it as instructions or log it.
"""

from __future__ import annotations

import asyncio
import importlib
import math
import re
from dataclasses import dataclass, replace
from importlib.metadata import version
from time import monotonic
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup

from scholarscope.fetcher import MAX_REDIRECTS, REDIRECT_STATUSES, USER_AGENT, Fetcher

RenderStatus = Literal[
    "ok", "blocked", "blocked_by_site", "timeout", "too_large", "render_error", "unavailable"
]


def validated_hosts(hosts: tuple[str, ...]) -> tuple[str, ...]:
    """Canonical explicit exact hostnames only; never infer ports/domains/wildcards."""
    if not isinstance(hosts, tuple):
        raise TypeError("allow_hosts must be a tuple of exact hostnames")
    result = []
    for host in hosts:
        if not isinstance(host, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host
        ):
            raise ValueError(
                "allow_hosts requires exact ASCII hostnames without ports or wildcards"
            )
        if len(host) > 253 or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in host.split(".")
        ):
            raise ValueError("invalid allow_hosts hostname")
        result.append(host.lower())
    return tuple(sorted(set(result)))


@dataclass(frozen=True)
class RenderResult:
    status: RenderStatus
    final_url: str | None = None
    html: bytes | None = None
    playwright_version: str | None = None
    browser_version: str | None = None
    blocked_requests: int = 0
    elapsed: float = 0
    error: str | None = None
    blocked_hosts: tuple[str, ...] = ()
    allow_hosts: tuple[str, ...] = ()


def _playwright() -> Any:
    try:
        return importlib.import_module("playwright.async_api")
    except ImportError:
        raise ImportError(
            "Optional renderer unavailable: install scholarscope[render], then playwright install chromium"
        ) from None


def bot_wall(html: bytes) -> bool:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if re.search(
        r"just a moment|checking your browser|verify you are human|access denied",
        title,
        re.IGNORECASE,
    ):
        return True
    if soup.select_one(
        "#captcha, .captcha, .g-recaptcha, .h-captcha, #challenge-running, #challenge-form"
    ):
        return True
    for tag in soup(["script", "style"]):
        tag.decompose()
    return bool(
        re.search(
            r"checking your browser before accessing|verify that you are human",
            soup.get_text(" "),
            re.IGNORECASE,
        )
    )


def _blocked(state: dict[str, Any], host: str | None, own_host: str) -> None:
    state["blocked_requests"] += 1
    if host and host != own_host:
        state["blocked_hosts"].add(host)
        state["blocked_hosts"] = set(sorted(state["blocked_hosts"])[:20])


def render(
    url: str,
    *,
    timeout: float = 20,
    settle_ms: int = 1500,
    max_bytes: int = 15_000_000,
    user_agent: str = USER_AGENT,
    allow_hosts: tuple[str, ...] = (),
) -> RenderResult:
    """Load + fixed settle only, with a cancellable overall budget including robots.

    No clicks, scrolling, logins, banner dismissal, downloads, stealth or retries.
    Cross-host main navigation is forbidden even if that host is explicitly
    allowed for subresources. Only successful HTML returns private UTF-8 DOM bytes.
    """
    hosts = validated_hosts(allow_hosts)
    if (
        not math.isfinite(timeout)
        or timeout <= 0
        or type(settle_ms) is not int
        or settle_ms < 0
        or type(max_bytes) is not int
        or max_bytes < 0
    ):
        raise ValueError("invalid renderer timeout, settle_ms or max_bytes")
    started = monotonic()
    state: dict[str, Any] = {
        "final_url": url,
        "blocked_requests": 0,
        "blocked_hosts": set(),
        "playwright_version": None,
        "browser_version": None,
        "error": None,
    }

    def outcome(
        status: RenderStatus, html: bytes | None = None, error: str | None = None
    ) -> RenderResult:
        return RenderResult(
            status,
            state["final_url"],
            html,
            state["playwright_version"],
            state["browser_version"],
            state["blocked_requests"],
            monotonic() - started,
            error,
            tuple(sorted(state["blocked_hosts"])[:20]),
            hosts,
        )

    async def work() -> RenderResult:
        try:
            original = httpx.URL(url).copy_with(fragment=None)
        except (httpx.InvalidURL, ValueError):
            return outcome("render_error", error="invalid_url")
        if (
            original.scheme not in {"http", "https"}
            or not original.host
            or original.username
            or original.password
        ):
            return outcome("render_error", error="HTTP(S) URL without credentials required")
        with Fetcher(
            user_agent=user_agent, timeout_seconds=timeout, max_bytes=max_bytes
        ) as fetcher:
            status, error = await fetcher.check_robots_async(original)
            if status != "ok":
                return outcome("blocked" if status == "blocked" else "render_error", error=error)
            try:
                api = _playwright()
            except ImportError as exc:
                return outcome("unavailable", error=str(exc))
            state["playwright_version"] = version("playwright")
            manager = api.async_playwright()
            driver = await manager.start()
            browser = None
            try:
                try:
                    browser = await driver.chromium.launch()
                except api.Error:
                    return outcome(
                        "unavailable", error="Chromium unavailable; run playwright install chromium"
                    )
                state["browser_version"] = browser.version
                context = await browser.new_context(
                    user_agent=user_agent, service_workers="block", accept_downloads=False
                )
                page = await context.new_page()
                lock = asyncio.Lock()
                visits: set[str] = set()
                navigation_count = 0
                pending: str | None = None

                def blocked(host: str | None) -> None:
                    _blocked(state, host, original.host)

                async def route_request(route: Any) -> None:
                    nonlocal navigation_count, pending
                    request = route.request
                    main = request.is_navigation_request() and request.frame == page.main_frame
                    current = httpx.URL(request.url).copy_with(fragment=None)
                    if request.is_navigation_request() and request.frame.page != page:
                        blocked(current.host)
                        await route.abort()
                        return
                    if request.is_navigation_request() and current.host != original.host:
                        blocked(current.host)
                        if main:
                            state["error"] = "redirect_host_change"
                        await route.abort()
                        return
                    if main:
                        if navigation_count > MAX_REDIRECTS or str(current) in visits:
                            blocked(current.host)
                            state["error"] = (
                                "redirect_limit"
                                if navigation_count > MAX_REDIRECTS
                                else "redirect_loop"
                            )
                            await route.abort()
                            return
                        visits.add(str(current))
                        navigation_count += 1
                        state["final_url"] = str(current)
                    if (
                        current.scheme not in {"http", "https"}
                        or current.username
                        or current.password
                        or current.host not in {original.host, *hosts}
                        or request.resource_type in {"image", "media", "font"}
                    ):
                        blocked(current.host)
                        await route.abort()
                        return
                    # A serialized asynchronous bridge avoids duplicate robots loads
                    # and applies per-host pacing before every permitted request.
                    async with lock:
                        seen: set[str] = set()
                        for hop in range(MAX_REDIRECTS + 1):
                            if current.username or current.password:
                                blocked(current.host)
                                if main:
                                    state["error"] = "credentials_in_url"
                                await route.abort()
                                return
                            if current.host not in {original.host, *hosts}:
                                blocked(current.host)
                                await route.abort()
                                return
                            status, reason = await fetcher.check_robots_async(current)
                            if status != "ok":
                                blocked(current.host)
                                if main:
                                    state["error"] = (
                                        "robots_blocked" if status == "blocked" else "robots_error"
                                    )
                                await route.abort()
                                return
                            await fetcher.wait_for_host_async(current)
                            response = await route.fetch(
                                url=str(current),
                                max_redirects=0,
                                max_retries=0,
                                timeout=max(1, (timeout - (monotonic() - started)) * 1000),
                            )
                            if response.status in REDIRECT_STATUSES:
                                target, reason = Fetcher._redirect_target(
                                    current,
                                    httpx.Response(response.status, headers=response.headers),
                                    hop,
                                    seen | {str(current)},
                                )
                                if target is None:
                                    blocked(
                                        httpx.URL(
                                            response.headers.get("location", str(current))
                                        ).host
                                    )
                                    if reason and "changes host" in reason:
                                        state["error"] = "redirect_host_change"
                                    elif main:
                                        state["error"] = "redirect_limit"
                                    await route.abort()
                                    return
                                if main:
                                    pending = str(target)
                                    blocked(current.host)
                                    await route.abort()
                                    return
                                seen.add(str(current))
                                current = target
                                continue
                            if main:
                                if response.status in {401, 403}:
                                    state["error"] = "site_access_denied"
                                    blocked(current.host)
                                    await route.abort()
                                    return
                                media = (
                                    response.headers.get("content-type", "")
                                    .split(";", 1)[0]
                                    .strip()
                                    .lower()
                                )
                                if media not in {"text/html", "application/xhtml+xml"}:
                                    state["error"] = "non_html_content"
                                    blocked(current.host)
                                    await route.abort()
                                    return
                                if not 200 <= response.status < 300:
                                    state["error"] = f"HTTP status {response.status}"
                                    blocked(current.host)
                                    await route.abort()
                                    return
                            await route.fulfill(response=response)
                            return

                async def guarded_route(route: Any) -> None:
                    try:
                        await route_request(route)
                    except Exception:  # noqa: BLE001 -- sanitize route failures before Playwright logs callbacks
                        if (
                            route.request.is_navigation_request()
                            and route.request.frame == page.main_frame
                            and pending is None
                            and state["error"] is None
                        ):
                            state["error"] = "request_failed"
                        try:
                            blocked(httpx.URL(route.request.url).host)
                            await route.abort()
                        except api.Error:
                            pass

                await context.route("**/*", guarded_route)

                async def websocket(ws: Any) -> None:
                    blocked(httpx.URL(ws.url).host)
                    await ws.close()

                await context.route_web_socket("**/*", websocket)
                target = str(original)
                while True:
                    pending = None
                    try:
                        await page.goto(target, wait_until="load", timeout=0)
                        await page.wait_for_timeout(settle_ms)
                    except api.Error:
                        if pending is None and state["error"] is None:
                            # A permitted script/meta navigation can interrupt
                            # goto; its guarded request already consumed a hop.
                            await page.wait_for_load_state("load", timeout=0)
                            await page.wait_for_timeout(settle_ms)
                    if state["error"]:
                        render_status: RenderStatus = (
                            "blocked"
                            if state["error"] == "robots_blocked"
                            else "blocked_by_site"
                            if state["error"] == "site_access_denied"
                            else "render_error"
                        )
                        return outcome(render_status, error=state["error"])
                    if pending is not None:
                        target = pending
                        # An aborted main navigation can leave Chromium's old
                        # document in transition even after goto raises. Replace
                        # that page before the next checked HTTP hop; keep the
                        # context (including cookies) and shared redirect budget.
                        await page.close()
                        page = await context.new_page()
                        continue
                    state["final_url"] = page.url
                    html = (await page.content()).encode("utf-8")
                    if len(html) > max_bytes:
                        return outcome("too_large", error="rendered HTML too large")
                    if bot_wall(html):
                        return outcome("blocked_by_site", error="bot_wall_marker")
                    return outcome("ok", html)
            finally:
                # Reserve part of the overall budget for teardown; no unbounded
                # cleanup can wait behind a hanging navigation.
                remaining = max(0.001, timeout - (monotonic() - started))
                try:
                    async with asyncio.timeout(remaining):
                        if browser is not None:
                            await browser.close()
                        await driver.stop()
                except TimeoutError:
                    pass

    async def bounded() -> RenderResult:
        reserve = min(0.5, timeout / 10)
        try:
            return await asyncio.wait_for(work(), timeout - reserve)
        except TimeoutError:
            return outcome("timeout", error="overall render timeout")
        except Exception as exc:  # noqa: BLE001 -- public render boundary must sanitize browser failures
            # Never echo arbitrary provider/page/browser exception bodies or URLs.
            return outcome("render_error", error=f"browser operation failed ({type(exc).__name__})")

    result = asyncio.run(bounded())
    return replace(result, elapsed=monotonic() - started)
