from __future__ import annotations

import hashlib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import ClassVar

import pytest

from scholarscope.fetcher import Fetcher


class FakeHandler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, tuple[int, bytes]]] = {}
    request_counts: ClassVar[dict[str, int]] = {}

    def do_GET(self) -> None:
        type(self).request_counts[self.path] = type(self).request_counts.get(self.path, 0) + 1
        if self.path == "/robots.txt":
            status, body = type(self).routes.get(self.path, (404, b""))
        else:
            status, body = type(self).routes.get(self.path, (404, b""))
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


@pytest.fixture
def fake_server() -> Iterator[tuple[str, type[FakeHandler]]]:
    FakeHandler.routes = {}
    FakeHandler.request_counts = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", FakeHandler
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_fetches_snapshots_hashes_and_caches(
    tmp_path, fake_server: tuple[str, type[FakeHandler]]
) -> None:
    base_url, handler = fake_server
    body = b"ScholarScope test page"
    handler.routes = {"/robots.txt": (200, b"User-agent: *\nAllow: /\n"), "/page": (200, body)}

    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        first = fetcher.fetch(f"{base_url}/page")
        second = fetcher.fetch(f"{base_url}/page")

    digest = hashlib.sha256(body).hexdigest()
    assert first.status == "ok", first.error
    assert first.content_sha256 == digest
    snapshot_path = first.snapshot_path
    assert snapshot_path == tmp_path / f"{digest}.bin"
    assert snapshot_path is not None
    assert snapshot_path.is_file()
    assert second.from_cache
    assert handler.request_counts["/page"] == 1


def test_robots_disallow_returns_blocked_without_fetching(
    tmp_path, fake_server: tuple[str, type[FakeHandler]]
) -> None:
    base_url, handler = fake_server
    handler.routes = {
        "/robots.txt": (200, b"User-agent: *\nDisallow: /private\n"),
        "/private": (200, b"must not fetch"),
    }

    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/private")

    assert result.status == "blocked"
    assert handler.request_counts.get("/private", 0) == 0


def test_http_404_returns_not_found(tmp_path, fake_server: tuple[str, type[FakeHandler]]) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": (404, b""), "/missing": (404, b"missing")}

    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/missing")

    assert result.status == "not_found"
    assert result.snapshot_path is None


def test_robots_http_403_returns_blocked(tmp_path, fake_server: tuple[str, type[FakeHandler]]) -> None:
    base_url, handler = fake_server
    handler.routes = {"/robots.txt": (403, b"denied"), "/page": (200, b"must not fetch")}

    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        result = fetcher.fetch(f"{base_url}/page")

    assert result.status == "blocked"
    assert handler.request_counts.get("/page", 0) == 0


def test_connection_failure_returns_network_error(tmp_path) -> None:
    with Fetcher(tmp_path, min_interval_seconds=0, timeout_seconds=0.1) as fetcher:
        result = fetcher.fetch("http://127.0.0.1:1/unreachable")

    assert result.status == "network_error"
