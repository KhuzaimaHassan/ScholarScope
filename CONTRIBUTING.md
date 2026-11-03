# Contributing to ScholarScope

Read the [README status table](README.md#project-status) and the relevant contract
under [docs/](docs) before proposing work. Built modules have synthetic tests;
there is no published accuracy baseline, web app or eligibility rule engine yet.
Use the existing [issue templates](.github/ISSUE_TEMPLATE) to discuss scope first.

## Development setup

Use Python 3.11 or newer. Clone the repo and create an isolated environment
outside the checkout, as shown in the [quickstart](README.md#quickstart).
Activate it, then run from the repository root:

```sh
python -m pip install -e ".[test]" ruff mypy
ruff check .
mypy .
pytest -q
```

The declared extras are `test` and `render`; there is no `dev` extra. Quality
tools are explicitly installed above. Tests use synthetic inputs, mock clients
and local HTTP servers; no real API keys or live providers/sites are needed.
Keep that property when adding tests. Do not add real scholarship page fixtures.

For optional browser coverage:

```sh
python -m pip install -e ".[render,test]"
python -m playwright install chromium
pytest -q -m browser tests/test_renderer.py -rs
```

Browser-marked tests skip with an explanation if the package/browser is missing.
[CI](.github/workflows/ci.yml) has a `quality` job running Ruff, pytest and mypy,
plus `render-tests`, which installs Chromium and uses local loopback fixtures.
The render job has `continue-on-error: true`: it is advisory, so read its actual
job result rather than assuming a green workflow means it passed. On Linux,
CI installs browser system dependencies with `playwright install --with-deps chromium`.

Manual provider/site runs are separate from these checks. Follow the
[local-snapshot instructions](README.md#manual-extraction-from-a-local-snapshot)
only when you intend to use your own configured provider. `.env` is not
automatically loaded, and scripts can expose page passages in their output.

## Changes and pull requests

- Create a focused branch from updated `main`; keep unrelated fixes separate.
- Use a descriptive title with a prefix such as `feat:`, `fix:` or `docs:`, as
  in the merged PR history. Use a normal merge commit after maintainer review;
  do not merge your own unreviewed work.
- Follow the [PR template](.github/pull_request_template.md). Explain the problem,
  behavior, validation and limits. Disclose AI assistance and which files it
  affected; mark human review only after actually reviewing every changed line.
- Use `Closes #number` only when the issue is fully addressed and closure is
  intended. Use `Refs #number` for partial work or documentation references.
- Run the check commands above. Report pass/fail and skipped browser coverage;
  report relevant evaluation evidence only if it was actually measured. Never
  substitute synthetic-test success for an accuracy claim.
- Add synthetic regression tests for behavior changes. Reuse FakeClient,
  MockTransport and local-server patterns; do not introduce live network tests.
- Before changing a contract, propose the decision in an
  [ADR](docs/adr/README.md), obtain maintainer agreement, then update affected
  contracts and tests. Do not silently rewrite an accepted policy.
- Respect transformation versions: cleaner, PDF extractor, segmenter, verifier,
  prompt/rendering changes can invalidate derived data or caches. Review the
  relevant ADR and [snapshot drift policy](docs/14-snapshots.md); never silently
  adopt a new baseline or migrate labels/snapshots.

## Privacy and source content

Never commit real profiles, private snapshots, raw HTML/PDF/text page contents,
keys, `.env`, private caches or human-audit context. Use fictional profiles and
page content in tests. [Ignore rules](.gitignore) cover `eval/snapshots/`, `.env`,
`.cache/`, `profiles/`, `*.profile.json` and report output except its placeholder;
ignore rules do not protect files already tracked or deliberately force-added.

Profile data must never be sent to an LLM or included in logs. Explicit profile
JSON dumps contain real values even though repr/errors are redacted; see
[doc 20](docs/20-profile.md). Private cache/report output can contain source text.
Do not attach it to an issue or PR without review and appropriate redaction.

Before each commit, inspect `git status` and `git diff --cached`. Also check:

```sh
git ls-files eval/snapshots
git ls-files .env .cache
```

Both commands should print nothing. Respect robots, terms, identifying user
agents, host restrictions and blocks; do not add a workaround for a denied
source. Rendering does not expand what a site's terms allow. Follow
[source-terms.md](docs/source-terms.md) and [ADR 007](docs/adr/007-public-gold-set-private-snapshots.md).

## Gold-label integrity

Gold labels are hand-written by the maintainer so they remain an independent
check on extraction. Contributions to `eval/gold/` are not accepted without
prior discussion. **AI-written or AI-prefilled gold labels are refused**, even
if a schema validator accepts them. AI may assist code, tooling or guide drafts;
it must not supply the maintainer's label values or supporting quotes.

Follow [doc 07](docs/07-labeling-guide.md). Mechanical SKELETON files are unfinished
placeholders, not labels or accuracy evidence. The validator deliberately rejects
them with `skeleton, not labeled by hand`; do not delete that guard, clear the
marker, or pretend it is a unit-test failure to fix. A genuine labeling change
must record the independent human work and follow maintainer review.

## Site owner takedown requests

Open an issue in the [repository issue tracker](https://github.com/KhuzaimaHassan/ScholarScope/issues)
and identify it as a site-owner removal/takedown request. Provide the affected
source URL, the repository reference if known, and what you want removed or
corrected. Point to the applicable terms or rights concern when available;
do not publish private page copies, personal information, credentials or
confidential correspondence. Consult the recorded source-specific notices and
contact routes in [source-terms.md](docs/source-terms.md).

The snapshot policy requires honoring takedown requests; this guide supplies an
issue-tracker route, not an invented email address or an automatic deletion API.
