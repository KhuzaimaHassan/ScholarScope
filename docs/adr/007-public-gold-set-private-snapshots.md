# ADR 007 — Public gold-set labels, private page snapshots by default

**Status:** Accepted · **Date:** 2026-10-12 (revised after review)

## Context
Reproducible accuracy claims need a shared benchmark, and results must not drift when websites change, so pages are frozen as snapshots. Publishing full copies of third-party pages raises copyright and terms-of-use questions. Compliance with robots.txt does not by itself settle those questions.

## Decision
- Store frozen snapshots for evaluation, **private by default**.
- The public repo contains: hand-written labels, content hashes, short supporting quotes with source URLs, the program list, and a **script that re-fetches snapshots**.
- A full snapshot is published only for a source whose terms or license clearly allow it, with that decision recorded per source family in `docs/source-terms.md`.
- Takedown requests are honored promptly.

## Consequences
- Anyone can re-run the benchmark by re-fetching, though pages may have changed; content hashes make drift visible.
- CI needs snapshots available (private storage or cache) for its eval subset.
- Source-terms review is required before a family enters the gold set.

## Alternatives considered
- Publish all snapshots: simplest reproducibility, highest legal risk.
- No snapshots: results drift and claims cannot be reproduced.
