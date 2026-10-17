# ScholarScope

ScholarScope is an evidence-first tool for researching fully funded scholarships and graduate programs.

## Problem

Applicants must collect deadlines, eligibility rules, funding terms, required documents, language-test thresholds, and recommender requirements from scattered web pages and PDFs. A missed condition or incorrect deadline can cost an entire application cycle.

ScholarScope is designed to turn an official program URL into a traceable requirement record: every displayed claim should link to its source passage, uncertain claims should be marked `unverified`, and eligibility verdicts should be computed by deterministic code rather than by an LLM.

## Project status

This repository is in the docs-first foundation phase. The product pipeline is planned but not yet implemented.

## Roadmap

- **M0 — Foundations and docs:** finalize project decisions, documentation, ADRs, repository hygiene, and CI.
- **M1 — Fetch, clean, segment:** fetch public pages and PDFs and produce stable passages.
- **M2 — Evidence-linked extraction:** produce typed requirement records with verified evidence.
- **M3 — Gold set and evaluation harness:** label the 36-program starting set and publish reproducible metrics.
- **M4 — Eligibility engine and checklist:** compute auditable verdicts and dated application plans.
- **M5 — API and UI:** provide the end-to-end web experience.
- **M6 — Deploy and polish:** publish a free-tier demo and improve reliability.
- **M7 — Open-source readiness:** document contribution, parser extensions, and release practices.

## Documentation

- [Product brief](docs/01-product-brief.md)
- [Architecture](docs/02-architecture.md)
- [Evaluation plan](docs/03-evaluation-plan.md)
- [Risks and diligence](docs/04-risks-and-diligence.md)
- [Milestones and issues](docs/05-milestones-and-issues.md)
- [Architecture decision records](docs/adr/README.md)
- [Gold-set candidates](docs/06-gold-set-candidates.md)
- [HTML cleaner and source offsets](docs/08-html-cleaner.md)

## Important limitations

ScholarScope is not affiliated with any scholarship provider. Information can become outdated or be wrong; applicants must confirm requirements and deadlines on the official source before applying.

## License

ScholarScope is released under the [MIT License](LICENSE).
