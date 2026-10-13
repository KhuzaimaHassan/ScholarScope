# ADR 001 — Backend in FastAPI, frontend in Next.js

**Status:** Accepted · **Date:** 2026-10-12

## Context
ScholarScope needs an async API (slow fetches, LLM calls, background jobs) and a web UI whose signature feature is a click-to-source evidence panel. The owner already ships FastAPI backends and Next.js frontends, and the goal includes a public demo built quickly on free tiers.

## Decision
Use **FastAPI** (Python) for the API and workers, and **Next.js** for the frontend.

## Consequences
- Python keeps the extraction, evaluation harness, and API in one language and ecosystem (Pydantic, httpx, Playwright, pytest).
- Next.js deploys easily to a free tier and supports the evidence side-panel UI.
- Two deployables to maintain (API and frontend); keep the OpenAPI schema as the contract between them.
- Contributors need Python for pipeline work and TypeScript only for UI work.

## Alternatives considered
- Django: heavier than needed, and not the owner's stack.
- A single Streamlit app: faster to start, but a weak fit for the evidence panel and for a polished public demo.
