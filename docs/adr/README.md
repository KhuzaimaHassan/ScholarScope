# Architecture Decision Records

These records capture the accepted architecture and policy decisions for ScholarScope. Update the relevant ADR when an implementation choice changes, and record a new version or ADR rather than silently changing a decision.

| ADR | Decision |
|---|---|
| [001](001-fastapi-and-nextjs.md) | FastAPI backend and Next.js frontend |
| [002](002-pydantic-structured-outputs.md) | Pydantic structured extraction outputs |
| [003](003-evidence-verification-is-code.md) | Evidence verification is deterministic code |
| [004](004-deterministic-eligibility-engine.md) | Eligibility is computed by a deterministic rule engine |
| [005](005-provider-agnostic-llm-interface.md) | Provider-agnostic LLM interface |
| [006](006-playwright-fallback-only.md) | Playwright is a fallback fetcher |
| [007](007-public-gold-set-private-snapshots.md) | Public labels with private snapshots by default |
| [008](008-unverified-fields-retained-but-excluded.md) | Unverified fields are retained but excluded from logic |
| [009](009-eligibility-rule-provenance.md) | Eligibility rules carry provenance |
| [010](010-two-axis-field-status.md) | Separate content status from evidence verification |
| [011](011-passage-ids-and-segmentation.md) | Deterministic passage IDs, source references and bounded segmentation |
| [012](012-verifier-matching-rules.md) | Formatting-only quote presence checks and original offsets |
| [013](013-field-group-extraction-and-wire-schemas.md) | Field-group wire schemas with local domain validation and mandatory verification |
| [014](014-prompt-injection-defenses.md) | Escaped fencing, literal URL provenance and advisory injection findings |
| [015](015-link-targets-in-cleaned-text.md) | Link-target metadata, synthetic anchor provenance and version-first snapshot drift |
| [016](016-evaluation-harness-failure-semantics.md) | Failure-aware offline evaluation and private human-support audit artifacts |
| [017](017-rendering-fallback.md) | Heuristic-only restricted rendering, exact-host policy and snapshot provenance |
