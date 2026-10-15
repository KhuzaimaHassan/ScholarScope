#!/usr/bin/env python3
"""Check robots.txt once per domain used by the 20-slot shortlist.

The output is metadata only and is intended to be pasted into
docs/source-terms.md. It does not fetch candidate pages.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser


USER_AGENT = "ScholarScopeBot/0.1 (+https://github.com/KhuzaimaHassan/ScholarScope)"

SLOT_URLS = [
    "https://studyat.nwpu.edu.cn/info/1009/10571.htm",
    "https://apply.buct.edu.cn/MasterwsPrograms_14732/list.htm",
    "https://cie.ecust.edu.cn/chinese_government_scholarship/",
    "https://gjs.nwafu.edu.cn/en/Scholarships/5d0265e2f358470e9467a341ca2d2b17.htm",
    "https://www.pk.emb-japan.go.jp/itpr_en/MEXT_Research_Scholarship.html",
    "https://www.uae.emb-japan.go.jp/itpr_en/r_mext2027.html",
    "https://www.hisf.or.jp/wp/wp-content/uploads/2026/06/2027_bosyuyoukou_foreigner_E.pdf",
    "https://www.rotary-yoneyama.or.jp/english/overseas",
    "https://www.upf.edu/web/emai/faqs",
    "https://www.uni-lj.si/en/projects/emai",
    "https://www.fri.uni-lj.si/en/node/22492",
    "https://www.marihe.eu/how-to-apply/",
    "https://www.universiteitleiden.nl/en/scholarships/sea/leiden-university-excellence-scholarship-lexs",
    "https://www.uva.nl/en/about-the-uva/organisation/faculties/amsterdam-law-school/education/scholarships/amsterdam-merit-scholarship.html",
    "https://www.ru.nl/en/education/scholarships/radboud-scholarship-programme",
    "https://www.utwente.nl/en/itc/education/study-costs/scholarships/scholarship-finder/nl-scholarship-university-of-twente/",
    "https://www.polimi.it/en/international-prospective-students/laurea-magistrale-programmes-equivalent-to-master-of-science/scholarships/merit-based-scholarships/",
    "https://www.polimi.it/en/prospective-students/how-much-does-it-cost/scholarships",
    "https://studyinitaly.esteri.it/ListaBandi/ScaricaFileBando?ID=DAAAANOaK1LibkB7ECh3HBAAAAC%2Bhvf6cpmh8o0yUHxEqf5QIkXTXBz42ed%2BQbTCWiD%2FaIKtTLftDI1Ql7Q6IJuG0kqBLoTF",
    "https://studyinitaly.esteri.it/ListaBandi",
]


def robots_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def check_domain(host: str, urls: list[str], checked: str) -> str:
    robots = robots_url(urls[0])
    parser = RobotFileParser()
    parser.set_url(robots)
    request = Request(robots, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read()
        parser.parse(body.decode("utf-8", errors="replace").splitlines())
        results = [
            "allowed" if parser.can_fetch(USER_AGENT, url) else "disallowed"
            for url in urls
        ]
        delay = parser.crawl_delay(USER_AGENT)
        delay_text = str(delay) if delay is not None else "none"
        return f"{', '.join(results)}; crawl-delay={delay_text}"
    except Exception as exc:  # network conditions are part of the recorded result
        return f"blocked from this network ({type(exc).__name__})"


def main() -> None:
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for url in SLOT_URLS:
        grouped.setdefault(urlparse(url).netloc, []).append(url)
    checked = date.today().isoformat()
    print("| Domain | robots.txt | Checked | Result for shortlist slot URL(s) |")
    print("|---|---|---|---|")
    for host, urls in grouped.items():
        result = check_domain(host, urls, checked)
        print(f"| `{host}` | `{robots_url(urls[0])}` | {checked} | {result} |")


if __name__ == "__main__":
    main()
