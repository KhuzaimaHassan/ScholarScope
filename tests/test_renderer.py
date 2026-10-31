"""Optional browser tests use loopback ONLY; core tests stub rendering/robots."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import socket
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

import scholarscope.renderer as rendering
from scholarscope.cleaner import clean_html
from scholarscope.fetcher import USER_AGENT, Fetcher, FetchResult
from scholarscope.llm.fake import FakeClient
from scholarscope.pipeline import prepare_page, run_pipeline
from scholarscope.renderer import RenderResult, render
from scholarscope.snapshots import SnapshotManifest, SnapshotRecord, classify_drift, snapshot_page

ROOT = Path(__file__).resolve().parents[1]
THIN = b"<main></main><script>/*" + b" " * 6000 + b"*/</script>"


@pytest.fixture(autouse=True)
def loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = socket.socket.connect
    resolve = socket.getaddrinfo

    def local_connect(sock: socket.socket, address: Any) -> Any:
        assert address[0] in {"127.0.0.1", "localhost", "::1"}, "non-loopback test connection"
        return connect(sock, address)

    def local_resolve(host: Any, *args: Any, **kwargs: Any) -> Any:
        assert host in {"127.0.0.1", "localhost", "::1", b"127.0.0.1", b"localhost"}, (
            "external test DNS"
        )
        return resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket, "getaddrinfo", local_resolve)


def fetched(body: bytes = THIN, **changes: Any) -> FetchResult:
    return FetchResult(
        url="http://127.0.0.1/page",
        status="ok",
        content=body,
        content_sha256=hashlib.sha256(body).hexdigest(),
        content_type="text/html",
        fetched_at="2026-10-31T10:00:00Z",
        **changes,
    )


@pytest.mark.parametrize(
    "status",
    ["blocked", "blocked_by_site", "timeout", "too_large", "render_error", "unavailable", "ok"],
)
def test_prepare_failure_never_falls_back(monkeypatch: pytest.MonkeyPatch, status: Any) -> None:
    monkeypatch.setattr(rendering, "render", lambda *a, **k: RenderResult(status, error="fixture"))
    result = prepare_page(fetched())
    assert (
        result.status == ("render_error" if status == "ok" else status)
        and result.error == "fixture"
    )
    assert result.fetch_result.fetch_mode == "http"


def test_prepare_rendered_dom_and_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"<main>A fictional rendered scholarship with a visible application requirement.</main>"
    seen = []

    def stub(url: str, **options: Any) -> RenderResult:
        seen.append(options)
        return RenderResult(
            "ok",
            url,
            body,
            "pw-fixture",
            "browser-fixture",
            2,
            blocked_hosts=("localhost",),
            allow_hosts=("localhost",),
        )

    monkeypatch.setattr(rendering, "render", stub)
    result = prepare_page(fetched(), allow_hosts=("localhost",))
    assert result.status == "ok"
    assert result.fetch_result.content == body
    assert result.fetch_result.fetch_mode == "rendered"
    assert result.fetch_result.content_sha256 == hashlib.sha256(body).hexdigest()
    assert seen[0]["user_agent"] == USER_AGENT and seen[0]["allow_hosts"] == ("localhost",)
    pipeline = run_pipeline(result.fetch_result, FakeClient())
    assert pipeline.record is not None  # normal pipeline, not a special parser


@pytest.mark.parametrize("case", ["small", "full", "pdf", "json", "blocked", "rendered", "local"])
def test_no_other_render_trigger(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("render attempted without suspiciously_empty HTTP HTML")

    monkeypatch.setattr(rendering, "render", forbidden)
    result = fetched()
    if case == "small":
        result = replace(result, content=b"<main>Small</main>", content_sha256=None)
    elif case == "full":
        result = replace(
            result, content=b"<main>" + b"Visible text. " * 500 + b"</main>", content_sha256=None
        )
    elif case in {"pdf", "json"}:
        result = replace(
            result, content_type="application/pdf" if case == "pdf" else "application/json"
        )
    elif case == "blocked":
        result = replace(result, status="blocked")
    elif case == "rendered":
        result = replace(result, fetch_mode="rendered")
    else:
        result = replace(result, final_url="file:///fictional.html")
    assert prepare_page(result).rendering is None


@pytest.mark.parametrize("status", ["blocked", "network_error"])
def test_robots_before_import_or_launch(monkeypatch: pytest.MonkeyPatch, status: Any) -> None:
    async def policy(*args: Any) -> Any:
        return status, "fixture policy"

    monkeypatch.setattr(Fetcher, "check_robots_async", policy)
    monkeypatch.setattr(rendering, "_playwright", lambda: pytest.fail("browser launched/imported"))
    result = render("http://127.0.0.1/private")
    assert result.status == ("blocked" if status == "blocked" else "render_error")


def test_missing_lazy_import(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allowed(*args: Any) -> Any:
        return "ok", None

    real_import = rendering.importlib.import_module

    def missing(name: str) -> Any:
        if name.startswith("playwright"):
            raise ImportError
        return real_import(name)

    monkeypatch.setattr(Fetcher, "check_robots_async", allowed)
    monkeypatch.setattr(rendering.importlib, "import_module", missing)
    result = render("http://127.0.0.1/page")
    assert result.status == "unavailable" and "playwright install chromium" in (result.error or "")


@pytest.mark.parametrize(
    "hosts",
    [("*.example.invalid",), ("https://localhost",), ("localhost:80",), ("bad..host",), ("-bad",)],
)
def test_allow_hosts_rejects_non_exact(hosts: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        rendering.validated_hosts(hosts)


def test_allow_hosts_canonical_and_capped_telemetry() -> None:
    assert rendering.validated_hosts(("LOCALHOST", "localhost")) == ("localhost",)
    state: dict[str, Any] = {"blocked_requests": 0, "blocked_hosts": set()}
    for i in reversed(range(30)):
        rendering._blocked(state, f"host{i:02d}.invalid", "own.invalid")
    rendering._blocked(state, "host00.invalid", "own.invalid")
    assert state["blocked_requests"] == 31
    assert sorted(state["blocked_hosts"]) == [f"host{i:02d}.invalid" for i in range(20)]


@pytest.mark.parametrize(
    "body",
    [
        b"<title>Just a moment</title>",
        b'<div id="captcha"></div>',
        b'<div class="g-recaptcha"></div>',
    ],
)
def test_bot_markers(body: bytes) -> None:
    assert rendering.bot_wall(body)
    assert not rendering.bot_wall(b"<main>Fictional scholarship description.</main>")


def test_manifest_back_compat_rendered_copy_and_drift(tmp_path: Path) -> None:
    original = snapshot_page(
        fetched(b"<main>Fictional scholarship requirements.</main>"),
        "fixture",
        snapshots_dir=tmp_path,
    )
    old = original.model_dump(mode="json")
    for name in ("fetch_mode", "playwright_version", "browser_version", "allow_hosts"):
        old.pop(name)
    legacy = SnapshotRecord.model_validate(old)
    assert legacy.fetch_mode == "http" and not legacy.allow_hosts
    dom = replace(
        fetched(b"<main>Fictional scholarship requirements.</main>"),
        fetch_mode="rendered",
        playwright_version="pw-fixture",
        browser_version="browser-fixture",
        allow_hosts=("localhost",),
    )
    new = snapshot_page(dom, "rendered-fixture", snapshots_dir=tmp_path)
    assert (tmp_path / "rendered-fixture.html").read_bytes() == dom.content
    assert classify_drift(original, new).classification == "tool_version_changed"
    for update in (
        {"playwright_version": "next"},
        {"browser_version": "next"},
        {"allow_hosts": ("extra.invalid", "localhost")},
    ):
        assert (
            classify_drift(new, new.model_copy(update=update)).classification
            == "tool_version_changed"
        )
    assert classify_drift(new, new).classification == "unchanged"
    validator = Draft202012Validator(
        json.loads((ROOT / "eval/schema/snapshot-manifest.schema.json").read_text(encoding="utf-8"))
    )
    for entry in (old, new.model_dump(mode="json")):
        validator.validate({"schema_version": "0.1", "snapshots": {entry["slug"]: entry}})
    manifest = SnapshotManifest(snapshots={new.slug: new})
    assert SnapshotManifest.model_validate_json(manifest.model_dump_json()) == manifest
    with pytest.raises(ValidationError):
        SnapshotRecord.model_validate({**old, "fetch_mode": "rendered"})


@pytest.fixture
def browser_runtime() -> None:
    if importlib.util.find_spec("playwright") is None:
        pytest.skip(
            "optional playwright missing; install scholarscope[render] and playwright install chromium"
        )
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as driver:
        try:
            browser = driver.chromium.launch()
        except Error:
            pytest.skip("optional Chromium missing; run playwright install chromium")
        browser.close()


@pytest.fixture
def local_site() -> Any:
    routes: dict[str, tuple[int, bytes, dict[str, str]]] = {}
    counts: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            counts[self.path] = counts.get(self.path, 0) + 1
            if self.path == "/hang":
                sleep(10)
            status, body, headers = routes.get(self.path, (404, b"", {}))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    routes["/robots.txt"] = (
        200,
        b"User-agent: *\nDisallow: /private\n",
        {"Content-Type": "text/plain"},
    )
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base, routes, counts
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def page(body: bytes) -> tuple[int, bytes, dict[str, str]]:
    return 200, body, {"Content-Type": "text/html"}


@pytest.mark.browser
def test_browser_js_after_load(browser_runtime: None, local_site: Any) -> None:
    base, routes, _ = local_site
    routes["/page"] = page(
        b"<main id='result'></main><script>addEventListener('load',()=>setTimeout(()=>document.querySelector('main').textContent='Fictional JS scholarship requirements.',50))</script>"
    )
    result = render(base + "/page", timeout=15, settle_ms=200)
    assert result.status == "ok", result.error
    assert b"Fictional JS scholarship requirements." in (result.html or b"")
    assert result.playwright_version and result.browser_version


@pytest.mark.browser
@pytest.mark.parametrize("allowed", [False, True])
def test_browser_cross_host_script_opt_in(
    browser_runtime: None, local_site: Any, allowed: bool
) -> None:
    base, routes, counts = local_site
    other = base.replace("127.0.0.1", "localhost")
    routes["/page"] = page(
        f"<main id='result'>Waiting.</main><script src='{other}/content.js?secret=fictional'></script>".encode()
    )
    routes["/content.js?secret=fictional"] = (
        200,
        b"document.querySelector('main').textContent='Fictional host script result.';",
        {"Content-Type": "text/javascript"},
    )
    result = render(
        base + "/page", timeout=15, settle_ms=100, allow_hosts=("localhost",) if allowed else ()
    )
    assert result.status == "ok", result.error
    assert ("Fictional host script result." in clean_html(result.html or b"").text) is allowed
    if not allowed:
        assert result.blocked_requests >= 1 and result.blocked_hosts == ("localhost",)
        assert "/content.js?secret=fictional" not in counts
    else:
        assert not result.blocked_hosts and counts["/content.js?secret=fictional"] == 1


@pytest.mark.browser
def test_browser_robots_no_launch(
    browser_runtime: None, local_site: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _, counts = local_site
    monkeypatch.setattr(
        rendering, "_playwright", lambda: pytest.fail("browser launched on robots block")
    )
    result = render(base + "/private")
    assert result.status == "blocked" and "/private" not in counts


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "bot",
        "huge",
        "hang",
        "pdf",
        "redirect",
        "loop",
        "same-host",
        "disallowed-hop",
        "resource-redirect",
    ],
)
def test_browser_boundaries(browser_runtime: None, local_site: Any, case: str) -> None:
    base, routes, counts = local_site
    path = "/page"
    kwargs: dict[str, Any] = {"timeout": 15, "settle_ms": 0}
    if case == "bot":
        routes[path] = page(b"<title>Just a moment</title><div id='captcha'></div>")
        expected = "blocked_by_site"
    elif case == "huge":
        routes[path] = page(b"<main>" + b"x" * 6000 + b"</main>")
        kwargs["max_bytes"] = 500
        expected = "too_large"
    elif case == "hang":
        path = "/hang"
        kwargs["timeout"] = 3
        expected = "timeout"
    elif case == "pdf":
        routes[path] = (200, b"%PDF fictional", {"Content-Type": "application/pdf"})
        expected = "render_error"
    elif case == "resource-redirect":
        routes[path] = page(
            b"<main>Fictional requirements.</main><script src='/redirect.js'></script>"
        )
        routes["/redirect.js"] = (
            302,
            b"",
            {"Location": base.replace("127.0.0.1", "localhost") + "/target"},
        )
        kwargs["allow_hosts"] = ("localhost",)
        expected = "render_error"
    else:
        target = (
            base.replace("127.0.0.1", "localhost") + "/target"
            if case == "redirect"
            else "/page"
            if case == "loop"
            else "/private"
            if case == "disallowed-hop"
            else "/target"
        )
        routes[path] = (302, b"", {"Location": target})
        routes["/target"] = page(b"<main>Fictional redirected scholarship.</main>")
        expected = (
            "blocked"
            if case == "disallowed-hop"
            else "ok"
            if case == "same-host"
            else "render_error"
        )
        if case == "redirect":
            kwargs["allow_hosts"] = (
                "localhost",
            )  # subresource permission never permits navigation
    started = monotonic()
    result = render(base + path, **kwargs)
    assert result.status == expected, result.error
    if case == "hang":
        assert monotonic() - started < 4
    if case in {"redirect", "resource-redirect"}:
        assert result.error == "redirect_host_change" and "/target" not in counts
    if case == "same-host":
        assert result.final_url == base + "/target"
    if case == "disallowed-hop":
        assert "/private" not in counts


@pytest.mark.parametrize(
    "code, expected",
    [
        (404, "ok"),
        (410, "ok"),
        (401, "blocked"),
        (403, "blocked"),
        (500, "network_error"),
        (302, "blocked"),
    ],
)
def test_async_robots_matches_sync(
    tmp_path: Path, local_site: Any, code: int, expected: str
) -> None:
    base, routes, counts = local_site
    routes["/robots.txt"] = (code, b"", {})
    with Fetcher(tmp_path, min_interval_seconds=0) as fetcher:
        async_status, _ = asyncio.run(fetcher.check_robots_async(httpx.URL(base + "/page")))
        assert async_status == expected
        assert fetcher._robots_allows(httpx.URL(base + "/page"))[0] == expected
    assert counts["/robots.txt"] == 1


@pytest.mark.browser
def test_browser_navigation_ceiling_and_images(browser_runtime: None, local_site: Any) -> None:
    base, routes, counts = local_site
    for i in range(7):
        routes[f"/step{i}"] = (302, b"", {"Location": f"/step{i + 1}"})
    result = render(base + "/step0", timeout=20, settle_ms=0)
    assert result.status == "render_error" and result.error == "redirect_limit"
    assert "/step6" not in counts
    routes["/page"] = page(b"<main>Fictional requirements.</main><img src='/image.png'>")
    result = render(base + "/page", timeout=15, settle_ms=50)
    assert result.status == "ok" and result.blocked_requests >= 1
    assert "/image.png" not in counts


def test_refetch_cli_allow_hosts_and_render_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = importlib.util.spec_from_file_location(
        "refetch_renderer_test", ROOT / "scripts/refetch_snapshots.py"
    )
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    gold = tmp_path / "gold"
    gold.mkdir()
    (gold / "fixture.json").write_text(
        json.dumps({"program_slug": "fixture", "source": {"url": "http://127.0.0.1/page"}}),
        encoding="utf-8",
    )
    seen: list[Any] = []
    monkeypatch.setattr(Fetcher, "fetch", lambda self, url: fetched())

    def stub(url: str, **options: Any) -> RenderResult:
        seen.append(options["allow_hosts"])
        return RenderResult(
            "blocked_by_site", url, blocked_hosts=("localhost",), error="bot_wall_marker"
        )

    monkeypatch.setattr(rendering, "render", stub)
    manifest = tmp_path / "manifest.json"
    code = cli.main(
        [
            "--gold-dir",
            str(gold),
            "--snapshots-dir",
            str(tmp_path / "private"),
            "--manifest",
            str(manifest),
            "--allow-host",
            "LOCALHOST",
            "--allow-host",
            "localhost",
            "--update-manifest",
        ]
    )
    assert code == 0 and seen == [("localhost",)]
    output = capsys.readouterr()
    assert "blocked_by_site" in output.out and "localhost" in output.err
    assert json.loads(manifest.read_text(encoding="utf-8"))["snapshots"] == {}
    assert not (tmp_path / "private/fixture.html").exists()
    assert cli.main(["--render"]) == 1  # force override intentionally absent
