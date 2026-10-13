# ADR 006 — Playwright only as a fallback fetcher

**Status:** Accepted · **Date:** 2026-10-12

## Context
Some program pages need JavaScript to render. A headless browser handles them but is slower, heavier, and costlier to host than plain HTTP fetching.

## Decision
The Fetcher tries **httpx** first. It falls back to **Playwright** only when the static response yields too little main-content text (threshold configurable and tested). Results are cached by content hash. The fetcher respects robots.txt, rate limits per host, and sends an identifying user agent.

## Consequences
- Most pages stay fast and cheap; JS-heavy pages cost extra latency on first fetch only.
- The "too little text" heuristic needs tests on real JS-heavy pages from the gold set.
- Playwright adds a heavier Docker image and a browser dependency for deployment.

## Alternatives considered
- Always use a headless browser: simpler logic but slower and costlier.
- Never render JavaScript: cheaper but fails on a share of real program pages.
