# 06 — Gold Set Candidates (v0.2 research update)

**Status:** Draft research update on 2026-10-14. Owner review required before labeling.
**Purpose:** Pick the 36 programs (nine families × four) for the evaluation set, and check source terms, layout mix, snapshot feasibility, and labeling workload before any labeling starts.

## How to read this file

Evidence level for each URL:

- **Fetched** — I opened the page and checked its content.
- **Seen** — the URL appeared in search results on an official or university domain; content not yet opened.
- **Mirror** — hosted by a different organization than the program owner (a university or embassy copy). Useful as a layout test, but the owner's own page is the better primary source.
- **Gap** — no official URL found yet. Do not label anything for this slot until a URL is confirmed.

Not done yet for any domain: robots.txt checks and terms-of-use review. Layout types below are expectations from the URL shape and search listing, except where marked Fetched. Third-party aggregator sites (scholarship blogs, listing portals) appeared in many results and are deliberately excluded.

## Coverage at a glance

Japan is one gold-set family. The MEXT and private-foundation sections below are candidate pools within that single family, not separate families or additive quotas. The final Japan set will contain four programs total; the recommended mix is two MEXT candidates and two private-foundation candidates.

| Family | Primary slots filled with a usable URL | Main gap |
|---|---|---|
| China — CSC | 4 of 4 (university-level pages) | No CSC / Type A official page found yet |
| Japan — one family (MEXT + foundations) | Candidate pools available; select 4 total | Prefer 2 MEXT and 2 foundation sources; need stronger primary-source coverage |
| Erasmus Mundus | 3 of 4 | Need a 4th programme (DEAI or another EMJM) |
| Netherlands | 1 of 4 | Official TU Delft, UvA, Radboud, Twente pages not found |
| Italy | 2 of 4 | Need MAECI / DSU / another university |
| Germany — DAAD | 0 of 4 official | Only mirrors seen; need daad.de pages |
| UK — Chevening | 0 of 4 official | Need chevening.org pages |
| US — Fulbright | 1 of 4 (mirror) | Need USEFP / foreign-student pages |
| South Korea — GKS | 3 of 4 (embassy notices, same notice) | Need Study in Korea / NIIED and a GKS-U university page |

Roughly 20 of 36 slots have a candidate, and about half of those are mirrors or near-duplicates. A second research pass is needed before labeling starts.

## Candidates by family

### 1. China — CSC (shortlist family)

| # | Program / page | URL | Level | Layout (expected) |
|---|---|---|---|---|
| 1 | NWPU — CSC-University Program | https://studyat.nwpu.edu.cn/info/1009/10571.htm | Seen | HTML, possibly multi-page |
| 2 | BUCT — Master programs listing | https://apply.buct.edu.cn/MasterwsPrograms_14732/list.htm | Seen | Multi-page list |
| 3 | ECUST — Chinese Government Scholarship | https://cie.ecust.edu.cn/chinese_government_scholarship/ | Seen | HTML |
| 4 | NWAFU — Scholarships | https://gjs.nwafu.edu.cn/en/Scholarships/5d0265e2f358470e9467a341ca2d2b17.htm | Seen | HTML |
| spare | BIT — Office of International Students FAQ | https://isc.bit.edu.cn/aboutbit/faq/3714638c555d436b815ec089176975e4.htm | Seen | FAQ page |
| spare | USST — Chinese Government Scholarship | https://isoe.usst.edu.cn/2019/1226/c9764a212605/page.htm | Seen | HTML (URL suggests a 2019 page; check currency) |

Notes: all six are university pages for the direct-application route. Replace one primary with the official CSC / Study in China page for the government route once found, so both types are covered. Chinese university pages are a good test for stale or inconsistent dates.

### 2. Japan — MEXT (shortlist family)

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | Embassy of Japan in Pakistan — MEXT Research Scholarship 2027 | https://www.pk.emb-japan.go.jp/itpr_en/MEXT_Research_Scholarship.html | **Fetched** | HTML; no eligibility list, documents listed; guidelines and forms link out to studyinjapan.go.jp; **applications closed (deadline 26 May 2026)** |
| 2 | Embassy of Japan in the UAE — MEXT 2027 Research Program | https://www.uae.emb-japan.go.jp/itpr_en/r_mext2027.html | Seen | HTML |
| 3 | Embassy of Japan in India — Research Student | https://www.in.emb-japan.go.jp/education/Research_Student.html | Seen | HTML |
| 4 | Embassy of Palestine page — MEXT PDF | https://www.ps.emb-japan.go.jp/files/101074448.pdf | Seen | **PDF** |
| spare | Embassy of Japan in Kuwait — 2027 MEXT | https://www.kw.emb-japan.go.jp/itpr_ja/11_000001_00345.html | Seen | HTML (Japanese path; check language) |
| spare | Embassy of Japan in Micronesia — 2027 application | https://www.micronesia.emb-japan.go.jp/itpr_ja/11_000001_01032.html | Seen | HTML (Japanese path; check language) |

Notes: these are the same programme published by different embassies, so they test consistency of extraction across wording and layout rather than five different programmes. Counting them as four separate gold programs would overstate diversity; I suggest labeling two embassy pages plus the official Study in Japan page (not yet found) plus the PDF.

### 3. Japan — private foundations (shortlist family)

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | Honjo International Scholarship Foundation — 2027 application guidelines (foundation's own) | https://www.hisf.or.jp/wp/wp-content/uploads/2026/06/2027_bosyuyoukou_foreigner_E.pdf | Seen | **PDF**, current cycle |
| 2 | Honjo via University of Tsukuba | https://www.tsukuba.ac.jp/en/admissions/financial-scholarships/individual/pdf/honjo20240325-en.pdf | Mirror | PDF, 2024 copy |
| 3 | Rotary Yoneyama via University of Tokyo (notice 1) | https://www.k.u-tokyo.ac.jp/en/information/category/scholarship/9156.html | Mirror | HTML |
| 4 | Rotary Yoneyama via University of Tokyo (notice 2) | https://www.k.u-tokyo.ac.jp/en/information/category/scholarship/9073.html | Mirror | HTML |
| spare | Rotary Yoneyama pre-announcement via Saitama University | https://en.saitama-u.ac.jp/studentlife/scholarship_list/rotary-yoneyama-memorial-foundation-2025fy-preannouncement | Mirror | HTML |
| spare | Honjo via Utsunomiya University | https://intl.utsunomiya-u.ac.jp/wp-content/uploads/2023/08/Guidline-for-Application2024.pdf | Mirror | PDF, 2024 |

Notes: only one page is the foundation's own. Mirrors that carry old-cycle details are useful as a deliberate stale-data test but should be labeled with their cycle year. Find the Rotary Yoneyama foundation's own site.

### 4. Erasmus Mundus (shortlist family)

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | EMAI — FAQs (Pompeu Fabra) | https://www.upf.edu/web/emai/faqs | Seen | HTML |
| 2 | EMAI — project page (University of Ljubljana) | https://www.uni-lj.si/en/projects/emai | Seen | HTML |
| 3 | EMAI — FRI Ljubljana | https://www.fri.uni-lj.si/en/node/22492 | Seen | HTML |
| 4 | Gap | — | — | Need DEAI or another AI/data EMJM, ideally a multi-page consortium site |

Notes: the EMAI slots are different partner pages for one programme, so they test consortium-style content spread across sites. A fourth distinct programme is needed.

### 5. Netherlands (shortlist family)

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | Leiden Excellence Scholarship (LExS) | https://www.universiteitleiden.nl/en/scholarships/sea/leiden-university-excellence-scholarship-lexs | Seen | HTML; also served under student. and staff. hostnames, which may duplicate content |
| 2 | Gap — TU Delft Justus & Louise van Effen | — | — | Official page not found yet |
| 3 | Gap — Amsterdam Merit Scholarship (UvA) | — | — | Official page not found yet |
| 4 | Gap — Radboud or Twente | — | — | Official page not found yet |

Notes: search results for TU Delft and UvA returned only third-party listings. Do not use those as sources.

### 6. Italy (shortlist family)

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | Politecnico di Milano — merit-based scholarships | https://www.polimi.it/en/international-prospective-students/laurea-magistrale-programmes-equivalent-to-master-of-science/scholarships/merit-based-scholarships/ | **Fetched** | Static HTML; **content is 2024-25**; deadlines sit in a linked document; full tuition waiver, allowance up to about €10,000/year |
| 2 | Politecnico di Milano — scholarships overview | https://www.polimi.it/en/prospective-students/how-much-does-it-cost/scholarships | Seen | HTML |
| 3 | Gap — MAECI / Study in Italy | — | — | Not found yet |
| 4 | Gap — DSU or another university | — | — | Not found yet |

Notes: the fetched Polimi page is a good example of the stale-cycle problem and of deadlines held in a separate document, which the pipeline must follow or mark as unverified.

### 7. Germany — DAAD-type

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | EPOS — development-related postgraduate courses (copy hosted by NDU Pakistan) | https://ndu.edu.pk/fcs/prsa-IT/news/2025/may/Development-Related Postgraduate-Courses(EPOS)•DAAD.pdf | Mirror | PDF, 2025 |
| 2 | DAAD scholarship programs (copy hosted by ITS Indonesia) | https://its.ac.id/international/wp-content/uploads/sites/66/2024/08/2024_08-DAAD-scholarship-programs.pdf | Mirror | PDF, 2024 |
| 3–4 | Gap | — | — | Need daad.de database or programme pages, including the Pakistan country page |

Notes: DAAD is deprioritized for your applications this cycle, so keep this family for breadth, but use official pages.

### 8. United Kingdom — Chevening-type

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | Apply to Chevening 2024-25 (copy hosted by KP Higher Education Department) | https://hed.gkp.pk/public/uploads/Apply to Chevening 2024-25 final.pdf | Mirror | PDF, 2024-25 |
| 2 | Same guide (copy hosted by Fatima Jinnah Women University) | https://www.fu.edu.pk/images/Events/Apply to Chevening 2024-25 final by Shahla.pdf | Mirror | PDF; possibly the same document |
| 3–4 | Gap | — | — | Need chevening.org eligibility, how-to-apply and country pages, plus another UK scholarship |

Notes: slots 1 and 2 may be the same underlying guide; verify before counting as two programs.

### 9. United States — Fulbright-type

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | 2026 Fulbright Student (Master's and PhD) Program (copy hosted by IBA Karachi) | https://osa.iba.edu.pk/oise/2026-fulbright-student-masters-and-phd-program.php | Mirror | HTML, 2026 |
| spare | Same notice, 2025 and 2024 editions on IBA | https://osa.iba.edu.pk/irc/2025-fulbright-student-masters-andphd-program.php | Mirror | HTML (year-over-year change test) |
| 2–4 | Gap | — | — | Need USEFP / Fulbright official pages and another US fully funded option |

### 10. South Korea — GKS-type

| # | Program / page | URL | Level | Layout |
|---|---|---|---|---|
| 1 | GKS notice on MOFA English site | https://www.mofa.go.kr/ke-en/brd/m_10538/view.do?seq=761541 | Seen | HTML notice (title contains Korean navigation text) |
| 2 | GKS notice, Greece embassy | https://gr.mofa.go.kr/gr-en/brd/m_6940/view.do?seq=761664 | Seen | HTML notice |
| 3 | GKS notice, Boston consulate | https://www.mofa.go.kr/us-boston-en/brd/m_4558/view.do?seq=761392 | Seen | HTML notice |
| 4 | Gap | — | — | Need Study in Korea / NIIED guidelines and a GKS-U university page |

Notes: these three are embassy copies of the same announcement, so they test cross-site consistency more than programme diversity.

## Layout mix so far

- **PDF:** Honjo 2027 guidelines, MEXT embassy PDF, Honjo mirrors, EPOS and Chevening copies, DAAD copy.
- **Multi-page or consortium:** EMAI partner pages, BUCT list, CSC universities.
- **JS-rendered:** none confirmed. The Pakistan embassy page's fetch output mentioned JavaScript, but the content was present. Before labeling, find at least four pages that need a browser (likely candidates are the university scholarship portals) so the Playwright fallback is actually tested.
- **Stale or closed cycle:** Polimi (2024-25), MEXT Pakistan (closed), several mirrors from 2024. Keep a few on purpose, labeled with their cycle year.

## Source-terms review (to do before labeling, per ADR 007)

For each domain in the final list, record in `docs/source-terms.md`:

- robots.txt result (not yet checked for any domain),
- link to the site's terms of use or copyright notice,
- whether full snapshots may be published (default: no, keep private),
- contact route for takedown requests.

Domains seen so far: nwpu.edu.cn, buct.edu.cn, ecust.edu.cn, nwafu.edu.cn, bit.edu.cn, usst.edu.cn, emb-japan.go.jp (several country sites), hisf.or.jp, tsukuba.ac.jp, u-tokyo.ac.jp, saitama-u.ac.jp, utsunomiya-u.ac.jp, upf.edu, uni-lj.si, fri.uni-lj.si, universiteitleiden.nl, polimi.it, ndu.edu.pk, its.ac.id, hed.gkp.pk, fu.edu.pk, iba.edu.pk, mofa.go.kr. Expect around 25 domains once gaps are filled.

## Labeling workload (rough estimate, to be replaced by a pilot)

Assumption: 12–15 fields per program with a supporting quote each, plus deadlines and conditions. At about 30–45 minutes per program, 36 programs take roughly 18–27 hours, plus 3–5 hours for the second pass on 10 programs and about 2 hours to audit evidence support on 50 fields. Label three programs first, time them, then update this estimate. Shortlist families (about 20 programs) come first.

## Decisions needed

1. Accept mirrors as gold programs, or require the owner's page? Suggested: allow mirrors only when the owner's page is unavailable, and mark them.
2. Count the same programme on several embassy or partner pages as one program or several? Suggested: at most two pages per programme, so 36 programs cover at least 24 distinct programmes.
3. Which gap-filling should come first? Suggested order: Netherlands, Italy, Erasmus fourth slot, CSC official page, then DAAD, Chevening, Fulbright, GKS.

## Next steps

1. Second research pass for gap slots using official domains only (daad.de, chevening.org, USEFP, studyinkorea, TU Delft, UvA, Radboud, Twente, MAECI, Erasmus Mundus programme sites, CSC portal).
2. Fetch each candidate to confirm content, cycle year, layout, and whether it renders without JavaScript.
3. Check robots.txt and terms for each domain; fill `docs/source-terms.md`.
4. Freeze the final 36-program list and close the "Choose the 36 programs" issue.

## Issue #7 research update — 2026-10-14

The following proposal uses official domains where the page was opened. `Fetched` means the page was opened and its content, cycle, and format were checked on 2026-10-14 or in the first research pass recorded above. `Seen` means an official-domain URL was located but not opened in this pass. `Gap` means no official URL was confirmed; it must not be labeled. JS status is `likely` when the page is an interactive finder, application system, or portal; it is not a claim that a browser was required during this pass.

Japan remains **one family with four total slots**. Its MEXT and private-foundation headings above are candidate pools; they are not additive quotas.

| Family | Slot | Proposed official page / program | Evidence | Cycle | Format; static/JS; language | Fields visible or expected |
|---|---:|---|---|---|---|---|
| CSC | 1 | [NWPU CSC-University Program](https://studyat.nwpu.edu.cn/info/1009/10571.htm) | Seen | unknown | HTML; unknown; English | eligibility, documents, deadline likely |
| CSC | 2 | [BUCT master-programme listing](https://apply.buct.edu.cn/MasterwsPrograms_14732/list.htm) | Seen | unknown | multi-page; likely JS; English | programmes, requirements, deadlines likely |
| CSC | 3 | [ECUST Chinese Government Scholarship](https://cie.ecust.edu.cn/chinese_government_scholarship/) | Seen | unknown | HTML; unknown; English | eligibility, funding, documents |
| CSC | 4 | [NWAFU scholarships](https://gjs.nwafu.edu.cn/en/Scholarships/5d0265e2f358470e9467a341ca2d2b17.htm) | Seen | unknown | HTML; unknown; English | scholarship types, requirements |
| Japan | 1 | [MEXT scholarship overview](https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/) | Fetched | current guidance; latest guidelines control | HTML; static content present; English | routes, degree types, age, education, funding |
| Japan | 2 | [MEXT research-student guidelines](https://www.studyinjapan.go.jp/en/_mt/2025/04/01-2026_Research_Guidelines_E.pdf) | Fetched | 2026 | PDF; static; English | eligibility, documents, schedule, funding |
| Japan | 3 | [JASSO scholarships](https://studyinjapan.go.jp/en/planning/scholarships/jasso-scholarships/) | Fetched | current page | HTML; static content present; English | eligibility, application route, funding |
| Japan | 4 | [Other scholarships](https://www.studyinjapan.go.jp/en/planning/scholarships/other-scholarships/) | Fetched | current page | HTML; static content present; English | private/local scholarships, source links |
| Erasmus Mundus | 1 | [EMAI FAQs](https://www.upf.edu/web/emai/faqs) | Seen | unknown | HTML; unknown; English | programme requirements, documents likely |
| Erasmus Mundus | 2 | [EMAI Ljubljana project page](https://www.uni-lj.si/en/projects/emai) | Seen | unknown | HTML; unknown; English | consortium, programme, funding likely |
| Erasmus Mundus | 3 | [EMAI FRI Ljubljana](https://www.fri.uni-lj.si/en/node/22492) | Seen | unknown | HTML; unknown; English | programme, deadlines likely |
| Erasmus Mundus | 4 | Official fourth EMJM programme page | Gap | — | — | Replace only after official page is opened |
| Netherlands | 1 | [Leiden Excellence Scholarship](https://www.universiteitleiden.nl/en/scholarships/sea/leiden-university-excellence-scholarship-lexs) | Seen | unknown | HTML; unknown; English | eligibility, funding, deadline |
| Netherlands | 2 | [Amsterdam Merit Scholarship](https://www.uva.nl/en/about-the-uva/organisation/faculties/amsterdam-law-school/education/scholarships/amsterdam-merit-scholarship.html) | Fetched | 2027–2028 | HTML; static content present; English | eligibility, deadline, funding |
| Netherlands | 3 | [Radboud Scholarship Programme](https://www.ru.nl/en/education/scholarships/radboud-scholarship-programme) | Fetched | 2027–2028 | HTML; static content present; English | eligibility, deadline, references, funding |
| Netherlands | 4 | [University of Twente NL Scholarship](https://www.utwente.nl/en/itc/education/study-costs/scholarships/scholarship-finder/nl-scholarship-university-of-twente/) | Fetched | 2027–2028 | HTML; scholarship finder path; likely JS; English | eligibility, GPA, English test, deadline, funding |
| Italy | 1 | [Politecnico merit scholarships](https://www.polimi.it/en/international-prospective-students/laurea-magistrale-programmes-equivalent-to-master-of-science/scholarships/merit-based-scholarships/) | Fetched in first pass | 2024–2025 | HTML; static; English | funding; deadline in linked document; stale cycle |
| Italy | 2 | [Politecnico scholarships overview](https://www.polimi.it/en/prospective-students/how-much-does-it-cost/scholarships) | Seen | unknown | HTML; unknown; English | scholarship types, funding |
| Italy | 3 | [MAECI 2026–2027 call](https://studyinitaly.esteri.it/ListaBandi/ScaricaFileBando?ID=DAAAANOaK1LibkB7ECh3HBAAAAC%2Bhvf6cpmh8o0yUHxEqf5QIkXTXBz42ed%2BQbTCWiD%2FaIKtTLftDI1Ql7Q6IJuG0kqBLoTF) | Fetched | 2026–2027 | PDF; static; English | eligibility, countries, deadline, funding |
| Italy | 4 | [Study in Italy calls page](https://studyinitaly.esteri.it/ListaBandi) | Fetched | 2025–2026 page; stale/closed | HTML; static content present; English/Italian | call links, contact, status; stale cycle |
| Germany — DAAD | 1 | [DAAD scholarships overview](https://www.daad.de/en/studying-in-germany/scholarships/daad-scholarships/) | Fetched | current overview | HTML; static content present; English | eligibility groups, funding, database link |
| Germany — DAAD | 2 | [EPOS scholarship database entry](https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database?detail=50076777) | Fetched in first pass | 2027/28 listed | HTML/database; likely JS tabs; English | eligibility, work experience, funding, documents |
| Germany — DAAD | 3 | Official DAAD programme page for a second distinct programme | Gap | — | — | Replace only after official page is opened |
| Germany — DAAD | 4 | Official DAAD programme page for a third distinct programme | Gap | — | — | Replace only after official page is opened |
| United Kingdom — Chevening | 1 | [Who can apply](https://www.chevening.org/scholarships/who-can-apply/) | Fetched | current cycle | HTML; static content present; English | degree level, programme, general eligibility |
| United Kingdom — Chevening | 2 | [Eligibility criteria](https://www.chevening.org/resource-hub/guidance/eligibility/) | Fetched | current cycle | HTML; static content present; English | nationality, return, work, degree, offers |
| United Kingdom — Chevening | 3 | [Application timeline](https://www.chevening.org/scholarships/application-timeline/) | Fetched | 2027–2028 | HTML; static content present; English | opening, closing, offer, interview dates |
| United Kingdom — Chevening | 4 | [Online application system guidance](https://www.chevening.org/resource-hub/guidance/online-application-system/) | Fetched | current cycle | HTML; interactive application guidance; likely JS; English | application sections, referees, documents |
| United States — Fulbright | 1 | [USEFP Fulbright Degree](https://www.usefp.org/scholarships/fulbright-degree.cfm) | Fetched | 2026; closed | HTML; static content present; English | degree, education, GRE, TOEFL, funding |
| United States — Fulbright | 2 | [USEFP Fulbright Scholar](https://www.usefp.org/scholarships/fulbright-scholar.cfm) | Fetched | 2026; deadline 28 Oct 2026 | HTML; static content present; English | degree, proposal, references, funding |
| United States — Fulbright | 3 | [USEFP Fulbright Degree FAQ](https://www.usefp.org/scholarships/fulbright-degree-FAQ.cfm) | Seen | 2026; closed | HTML; unknown; English | GRE, TOEFL, eligibility clarifications |
| United States — Fulbright | 4 | Official USEFP current graduate-program page distinct from the Degree page | Gap | — | — | Replace only after official page is opened |
| South Korea — GKS | 1 | [2026 GKS Graduate notice](https://www.studyinkorea.go.kr/en/plan/gksNoticeRead.do?bbsId=BBSMSTR_000000000461&nttId=4420) | Fetched | 2026 | HTML notice plus attachments; likely JS; English/Korean | track, guidelines, university list, documents |
| South Korea — GKS | 2 | [2027 GKS Undergraduate University Track](https://www.studyinkorea.go.kr/en/plan/gksNoticeRead.do?bbsId=BBSMSTR_000000000461&nttId=4527) | Fetched | 2027 | HTML notice plus spreadsheet; likely JS; English/Korean | universities, schedule, application route |
| South Korea — GKS | 3 | [GKS programme page](https://studyinkorea.go.kr/ko/plan/scholarship.do?tab=gks-tab4) | Fetched | current page | HTML; interactive tabs; likely JS; Korean/English content | eligibility, GPA, nationality, funding |
| South Korea — GKS | 4 | [GKS programme overview](https://www.studyinkorea.go.kr/en/plan/gksNoticeRead.do?bbsId=BBSMSTR_000000000461&nttId=4385) | Seen | 2026 | HTML notice plus PDF; likely JS; English/Korean | application schedule, documents, university list |

### Count and quality check

- 9 families × 4 slots = 36 slots.
- No URL is repeated in this proposal.
- Japan is counted once and contributes four slots total.
- Four or more likely-JS pages are present: BUCT, Twente scholarship finder, Chevening application guidance, GKS notices/programme tabs, and DAAD database tabs. This is a test hypothesis; the fetcher must confirm whether static text is sufficient.
- Remaining `Gap` slots are intentionally not labeled. They require another official-domain research pass before the gold set can be frozen.

### Owner decisions before freezing

1. Accept or reject the use of official university pages as CSC evidence versus requiring a CSC portal page.
2. Accept or reject the three partner pages for EMAI and choose a fourth official EMJM programme.
3. Choose official replacements for the two DAAD gaps and one Fulbright gap.
4. Decide whether the repeated Chevening guidance pages should count as four evaluation pages or be reduced to two pages plus two distinct official country/programme pages.
5. Accept the intentional stale-cycle entries (Polimi 2024–25, closed Fulbright 2026, and closed Study in Italy 2025–26) as stale-data tests.
6. Review all `needs owner review` rows in `docs/source-terms.md`; keep full snapshots private unless explicit permission is recorded.
