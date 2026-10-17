from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import SHUT_RDWR
from threading import Thread
from typing import ClassVar

import pytest

from scholarscope.fetcher import USER_AGENT, Fetcher

Route = tuple[int, bytes] | tuple[int, bytes, dict[str, str]] | None
FakeServer = tuple[str, type["FakeHandler"]]


class FakeHandler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, Route]] = {}
    request_counts: ClassVar[dict[str, int]] = {}
    user_agents: ClassVar[list[str | None]] = []

    def do_GET(self) -> None:
        type(self).request_counts[self.path] = type(self).request_counts.get(self.path, 0) + 1
        type(self).user_agents.append(self.headers.get("User-Agent"))
        route = type(self).routes.get(self.path, (404, b""))
        if route is None:
            self.connection.shutdown(SHUT_RDWR)
            self.connection.close()
            return
        status, body = route[:2]
        headers = route[2] if len(route) == 3 else {}
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


@pytest.fixture
def fake_server() -> Iterator[FakeServer]:
    FakeHandler.routes = {}
    FakeHandler.request_counts = {}
    FakeHandler.user_agents = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", FakeHandler
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def assert_utc_timestamp(value: str | None) -> None:
    assert value is not None
    assert datetime.fromisoformat(value).tzinfo == UTC


def test_fetches_snapshots_hashes_and_caches(tmp_path: Path, fake_server: FakeServer) -> None:
    base_url, handler = fake_server
    body = b"ScholarScope fictional test page"
    handler.routes = {"/robots.txt": (200, b"User-agent: *\nAllow: /\n"), "/page": (200, body)}
    snapshot_dir = tmp_path / "fetched"
    hand_saved = tmp_path / "label.html"
    hand_saved.write_bytes(b"fictional hand-saved labeling copy")

    with Fetcher(snapshot_dir, min_interval_seconds=0) as fetcher:
        first = fetcher.fetch(f"{base_url}/page")
        second = fetcher.fetch(f"{base_url}/page")

    digest = hashlib.sha256(body).hexdigest()
    assert first.status == "ok", first.error
    assert first.content_sha256 == digest
    assert len(digest) == 64 and digest == digest.lower()
    assert first.snapshot_path == snapshot_dir / f"{digest}.bin"
    assert first.snapshot_path is not None
    assert first.snapshot_path.read_bytes() == body
    assert first.content == body
    assert first.http_status == 200
    assert first.final_url == f"{base_url}/page"
    assert first.content_type is None
    assert_utc_timestamp(first.fetched_at)
    assert not first.from_cache
    assert second.from_cache
    assert second.fetched_at == first.fetched_at
    assert second.snapshot_path == first.snapshot_path
    assert handler.request_counts == {"/robots.txt": 1, "/page": 1}
    assert handler.user_agents == [USER_AGENT, USER_AGENT]
    assert hand_saved.read_bytes() == b"fictional hand-saved labeling copy"


def test_new_fetcher_refetches_despite_existing_snapshot(
    tmp_path: Path, fake_server: FakeServer
) -> None:
    base_url, handler = fake_server
    handler.routes = {"/page": (200, b"fictional content")}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        first = fetcher.fetch(f"{base_url}/page")
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        second = fetcher.fetch(f"{base_url}/page")

    assert first.status == second.status == "ok"
    assert not second.from_cache
    assert first.snapshot_path == second.snapshot_path
    assert len(list(tmp_path.iterdir())) == 1
    assert handler.request_counts == {"/robots.txt": 2, "/page": 2}


def test_robots_disallow_returns_blocked_without_fetching(
    tmp_path: Path, fake_server: FakeServer
) -> None:
    base_url, handler = fake_server
    handler.routes = {
        "/robots.txt": (200, b"User-agent: *\nDisallow: /private\n"),
        "/private": (200, b"must not fetch"),
    }
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/private")

    assert result.status == "blocked"
    assert "disallowed by robots.txt" in (result.error or "")
    assert result.http_status is None
    assert result.content_type is None
    assert_utc_timestamp(result.fetched_at)
    assert handler.request_counts == {"/robots.txt": 1}
    assert not list(tmp_path.iterdir())


def test_http_404_returns_not_found(tmp_path: Path, fake_server: FakeServer) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": (404, b""), "/missing": (404, b"missing")}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/missing")

    assert result.status == "not_found"
    assert result.snapshot_path is None
    assert result.http_status == 404
    assert result.final_url == f"{base_url}/missing"
    assert_utc_timestamp(result.fetched_at)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("status_code", [401, 403, 429, 500, 503])
def test_page_http_errors(tmp_path: Path, fake_server: FakeServer, status_code: int) -> None:
    base_url, handler = fake_server
    handler.routes = {"/page": (status_code, b"fictional failure", {"Content-Type": "TEXT/HTML"})}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == ("blocked" if status_code in {401, 403} else "network_error")
    assert str(status_code) in (result.error or "")
    assert result.http_status == status_code
    assert result.content_type == "text/html"
    assert result.final_url == f"{base_url}/page"
    assert_utc_timestamp(result.fetched_at)
    assert result.snapshot_path is None
    assert result.content_sha256 is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("status_code", [401, 403])
def test_robots_http_access_denied_returns_blocked(
    tmp_path: Path, fake_server: FakeServer, status_code: int
) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": (status_code, b"denied"), "/page": (200, b"must not fetch")}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "blocked"
    assert f"robots.txt access denied: HTTP status {status_code}" in (result.error or "")
    assert result.http_status is None
    assert handler.request_counts == {"/robots.txt": 1}


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_robots_http_error_returns_network_error(
    tmp_path: Path, fake_server: FakeServer, status_code: int
) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": (status_code, b"unavailable")}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "network_error"
    assert f"robots.txt HTTP status {status_code}" in (result.error or "")
    assert handler.request_counts == {"/robots.txt": 1}


@pytest.mark.parametrize("status_code", [404, 410])
def test_missing_robots_allows_fetch(
    tmp_path: Path, fake_server: FakeServer, status_code: int
) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": (status_code, b"missing"), "/page": (200, b"fictional page")}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "ok"
    assert handler.request_counts == {"/robots.txt": 1, "/page": 1}


def test_connection_failure_returns_network_error(tmp_path: Path, fake_server: FakeServer) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": None}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "network_error"
    assert "robots.txt network error" in (result.error or "")
    assert result.final_url == f"{base_url}/page"
    assert result.http_status is None
    assert_utc_timestamp(result.fetched_at)
    assert handler.request_counts == {"/robots.txt": 1}
    assert not list(tmp_path.iterdir())


def test_page_connection_failure_returns_network_error(
    tmp_path: Path, fake_server: FakeServer
) -> None:
    base_url, handler = fake_server
    handler.routes = {"/page": None}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "network_error"
    assert "HTTP request failed" in (result.error or "")
    assert result.http_status is None
    assert handler.request_counts == {"/robots.txt": 1, "/page": 1}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", ["ftp://127.0.0.1/page", "file:///etc/passwd"])
def test_non_http_scheme_makes_no_requests(
    tmp_path: Path, fake_server: FakeServer, url: str
) -> None:
    _, handler = fake_server
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(url)

    assert result.status == "network_error"
    assert result.error == "URL must use HTTP or HTTPS"
    assert result.final_url is None
    assert result.http_status is None
    assert_utc_timestamp(result.fetched_at)
    assert handler.request_counts == {}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
def test_same_host_redirect_allowed(
    tmp_path: Path, fake_server: FakeServer, status_code: int
) -> None:
    base_url, handler = fake_server
    handler.routes = {
        "/start": (status_code, b"", {"Location": "/target"}),
        "/target": (200, b"fictional target", {"Content-Type": "text/html; charset=utf-8"}),
    }
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/start")

    assert result.status == "ok"
    assert result.url == f"{base_url}/start"
    assert result.final_url == f"{base_url}/target"
    assert result.http_status == 200
    assert result.content_type == "text/html"
    assert handler.request_counts == {"/robots.txt": 1, "/start": 1, "/target": 1}


def test_cross_host_redirect_blocked_before_target_request(
    tmp_path: Path, fake_server: FakeServer
) -> None:
    base_url, handler = fake_server
    target = f"{base_url.replace('127.0.0.1', 'localhost')}/target"
    handler.routes = {"/start": (302, b"", {"Location": target}), "/target": (200, b"forbidden")}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/start")

    assert result.status == "blocked"
    assert "redirect changes host" in (result.error or "")
    assert result.final_url == f"{base_url}/start"
    assert result.http_status == 302
    assert handler.request_counts == {"/robots.txt": 1, "/start": 1}
    assert not list(tmp_path.iterdir())


def test_redirect_loop_stopped(tmp_path: Path, fake_server: FakeServer) -> None:
    base_url, handler = fake_server
    handler.routes = {
        "/start": (302, b"", {"Location": "/again"}),
        "/again": (302, b"", {"Location": "/start"}),
    }
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/start")

    assert result.status == "blocked"
    assert "redirect loop" in (result.error or "")
    assert result.final_url == f"{base_url}/again"
    assert handler.request_counts == {"/robots.txt": 1, "/start": 1, "/again": 1}


@pytest.mark.parametrize("hops", [5, 6])
def test_redirect_hop_limit(tmp_path: Path, fake_server: FakeServer, hops: int) -> None:
    base_url, handler = fake_server
    handler.routes = {f"/{i}": (302, b"", {"Location": f"/{i + 1}"}) for i in range(hops)}
    handler.routes[f"/{hops}"] = (200, b"fictional final page")
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/0")

    assert result.final_url == f"{base_url}/5"
    if hops == 5:
        assert result.status == "ok"
        assert handler.request_counts["/5"] == 1
    else:
        assert result.status == "blocked"
        assert "redirect hop limit exceeded" in (result.error or "")
        assert handler.request_counts.get("/6", 0) == 0
        assert not list(tmp_path.iterdir())


def test_redirect_into_disallowed_path_blocked(tmp_path: Path, fake_server: FakeServer) -> None:
    base_url, handler = fake_server
    handler.routes = {
        "/robots.txt": (200, b"User-agent: *\nDisallow: /private\n"),
        "/start": (302, b"", {"Location": "/private"}),
        "/private": (200, b"forbidden"),
    }
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/start")

    assert result.status == "blocked"
    assert "disallowed by robots.txt" in (result.error or "")
    assert "/private" in (result.error or "")
    assert result.final_url == f"{base_url}/start"
    assert result.http_status == 302
    assert handler.request_counts == {"/robots.txt": 1, "/start": 1}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("location", [None, "file:///etc/passwd"])
def test_unusable_redirect_blocked(
    tmp_path: Path, fake_server: FakeServer, location: str | None
) -> None:
    base_url, handler = fake_server
    headers = {} if location is None else {"Location": location}
    handler.routes = {"/start": (302, b"", headers)}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/start")

    assert result.status == "blocked"
    assert "redirect" in (result.error or "")
    assert handler.request_counts == {"/robots.txt": 1, "/start": 1}


@pytest.mark.parametrize(
    ("header", "content_type", "extension", "body"),
    [
        ("Text/HTML; Charset=UTF-8", "text/html", "html", b"<p>Fictional requirement</p>"),
        ("APPLICATION/PDF; version=1.7", "application/pdf", "pdf", b"%PDF-fictional fixture"),
    ],
)
def test_html_and_pdf_metadata_and_extensions(
    tmp_path: Path,
    fake_server: FakeServer,
    header: str,
    content_type: str,
    extension: str,
    body: bytes,
) -> None:
    base_url, handler = fake_server
    handler.routes = {"/page": (200, body, {"Content-Type": header})}
    with Fetcher(tmp_path / "fetched", min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "ok"
    assert result.content_type == content_type
    assert result.final_url == f"{base_url}/page"
    assert result.http_status == 200
    assert_utc_timestamp(result.fetched_at)
    assert result.snapshot_path == tmp_path / "fetched" / f"{hashlib.sha256(body).hexdigest()}.{extension}"
    assert result.snapshot_path.read_bytes() == body


@pytest.mark.parametrize("body", [b"12345678", b"123456789"])
def test_response_size_cap(tmp_path: Path, fake_server: FakeServer, body: bytes) -> None:
    base_url, handler = fake_server
    handler.routes = {"/page": (200, body, {"Content-Type": "text/html"})}
    snapshot_dir = tmp_path / "fetched"
    with Fetcher(snapshot_dir, min_interval_seconds=0, max_bytes=8) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.http_status == 200
    assert result.final_url == f"{base_url}/page"
    assert result.content_type == "text/html"
    assert_utc_timestamp(result.fetched_at)
    if len(body) == 8:
        assert result.status == "ok"
        assert result.snapshot_path is not None
        assert result.snapshot_path.read_bytes() == body
    else:
        assert result.status == "network_error"
        assert result.error == "response too large"
        assert result.snapshot_path is None
        assert result.content_sha256 is None
        assert result.content is None
        assert not snapshot_dir.exists()


def test_robots_redirect_not_followed(tmp_path: Path, fake_server: FakeServer) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": (302, b"", {"Location": "/other-robots"})}
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "blocked"
    assert "robots.txt redirect not followed" in (result.error or "")
    assert handler.request_counts == {"/robots.txt": 1}
