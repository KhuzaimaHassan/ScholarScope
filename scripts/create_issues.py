#!/usr/bin/env python3
"""Create GitHub labels, milestones, child issues and tracking issues from
docs/05-milestones-and-issues.md using the GitHub CLI (`gh`).

Usage:
    python3 scripts/create_issues.py --dry-run
    python3 scripts/create_issues.py --repo KhuzaimaHassan/scholarscope
    python3 scripts/create_issues.py --repo OWNER/REPO --plan docs/05-milestones-and-issues.md

Behavior:
  * --dry-run prints everything that would be created and touches nothing.
  * Re-running is safe: existing labels are updated, existing milestones and
    issues (matched by exact title) are skipped.
  * Child issues are created first, then one tracking issue per milestone with
    a checklist linking to its children.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

LABELS = {
    "type:docs": ("0075ca", "Documentation work"),
    "type:feature": ("a2eeef", "New functionality"),
    "type:eval": ("d4c5f9", "Evaluation set, metrics, harness"),
    "type:infra": ("bfd4f2", "Infrastructure, CI, deployment"),
    "type:bug": ("d73a4a", "Something is broken"),
    "good first issue": ("7057ff", "Good for newcomers"),
    "delegate:ai": ("fbca04", "4D Delegation: AI drafts, human reviews"),
    "delegate:human": ("0e8a16", "4D Delegation: human owns this"),
    "delegate:pair": ("c2e0c6", "4D Delegation: human and AI together"),
    "risk": ("b60205", "Risk mitigation work"),
    "blocked": ("000000", "Blocked by another issue"),
    "tracking": ("5319e7", "Milestone tracking issue"),
}

DEFINITION_OF_DONE = (
    "Acceptance criteria met, tests added, docs updated, eval subset not "
    "regressed, PR reviewed by the owner."
)

MILESTONE_RE = re.compile(r"^##\s+(M\d+)\s+[—-]\s+(.+?)\s*$")
GOAL_RE = re.compile(r"^\*\*Goal:\*\*\s*(.+?)\s*$")
ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def parse_plan(path: Path):
    """Return a list of milestones: {key, title, goal, notes, issues[]}."""
    milestones = []
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        m = MILESTONE_RE.match(line)
        if m:
            current = {
                "key": m.group(1),
                "title": f"{m.group(1)} — {m.group(2)}",
                "goal": "",
                "notes": [],
                "issues": [],
            }
            milestones.append(current)
            continue
        if current is None:
            continue
        if line.startswith("## ") and not MILESTONE_RE.match(line):
            current = None  # a non-milestone section ends parsing
            continue
        g = GOAL_RE.match(line)
        if g:
            current["goal"] = g.group(1)
            continue
        if line.startswith("**") and not line.startswith("**Goal:**"):
            current["notes"].append(line)
            continue
        r = ROW_RE.match(line)
        if r:
            cells = [c.strip() for c in r.group(1).split("|")]
            if len(cells) != 4:
                continue
            if cells[0].lower() == "issue" or set(cells[0]) <= {"-", " ", ":"}:
                continue
            title, typ, deleg, accept = cells
            current["issues"].append(
                {"title": title, "type": typ, "delegation": deleg, "accept": accept}
            )
    return milestones


def labels_for(issue):
    labels = []
    typ = issue["type"].lower()
    labels.append("risk" if typ == "risk" else f"type:{typ}")
    labels.append(f"delegate:{issue['delegation'].lower()}")
    return labels


def child_body(ms, issue):
    return (
        f"**Milestone:** {ms['title']}\n\n"
        f"## Acceptance criteria\n- [ ] {issue['accept']}\n\n"
        f"## Definition of done\n{DEFINITION_OF_DONE}\n\n"
        f"## 4D\n"
        f"- Delegation: `{issue['delegation']}`\n"
        f"- Description: write the spec or prompt from the docs before any AI-assisted work\n"
        f"- Discernment: review output against the acceptance criteria and eval metrics\n"
        f"- Diligence: note in the PR what was AI-generated and confirm you understand every line\n\n"
        f"_Source: docs/05-milestones-and-issues.md_"
    )


def tracking_body(ms, children):
    lines = [f"**Goal:** {ms['goal']}", ""]
    lines.extend(ms["notes"])
    if ms["notes"]:
        lines.append("")
    lines.append("## Issues")
    for issue, ref in children:
        lines.append(f"- [ ] {ref} {issue['title']}")
    lines += ["", "## Milestone gate",
              "All child issues closed and eval numbers recorded (where the milestone affects them).",
              "", "_Source: docs/05-milestones-and-issues.md_"]
    return "\n".join(lines)


def gh(args, dry, capture=True, input_text=None):
    cmd = ["gh"] + args
    if dry:
        print("  [dry-run] " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
        return ""
    res = subprocess.run(cmd, check=False, capture_output=capture, text=True, input=input_text)
    if res.returncode != 0:
        sys.exit(f"gh failed: {' '.join(cmd[:6])}\n{res.stderr.strip()}")
    return res.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="OWNER/REPO (required unless --dry-run)")
    ap.add_argument("--plan", default="docs/05-milestones-and-issues.md")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.repo:
        ap.error("--repo is required unless --dry-run is set")

    plan = Path(args.plan)
    if not plan.exists():
        sys.exit(f"Plan file not found: {plan}")
    milestones = parse_plan(plan)
    if not milestones:
        sys.exit("No milestones parsed; check the plan file format.")

    repo = args.repo or "OWNER/REPO"
    dry = args.dry_run
    total_children = sum(len(m["issues"]) for m in milestones)
    print(f"Plan: {len(milestones)} milestones, {total_children} child issues, "
          f"{len(milestones)} tracking issues, {len(LABELS)} labels")

    print("\nLabels")
    for name, (color, desc) in LABELS.items():
        print(f"  {name}")
        gh(["label", "create", name, "--color", color, "--description", desc,
            "--force", "--repo", repo], dry)

    existing_ms = {}
    existing_issues = {}
    if not dry:
        out = gh(["api", f"repos/{repo}/milestones?state=all&per_page=100"], dry)
        existing_ms = {m["title"]: m["number"] for m in json.loads(out or "[]")}
        out = gh(["issue", "list", "--repo", repo, "--state", "all", "--limit", "1000",
                  "--json", "number,title"], dry)
        existing_issues = {i["title"]: i["number"] for i in json.loads(out or "[]")}

    for ms in milestones:
        print(f"\n{ms['title']}")
        if ms["title"] in existing_ms:
            print("  milestone exists, skipping")
        else:
            gh(["api", f"repos/{repo}/milestones", "-f", f"title={ms['title']}",
                "-f", f"description={ms['goal']}"], dry)

        children = []
        for issue in ms["issues"]:
            title = issue["title"]
            print(f"  child: {title}  [{', '.join(labels_for(issue))}]")
            if title in existing_issues:
                children.append((issue, f"#{existing_issues[title]}"))
                print("    exists, skipping")
                continue
            cmd = ["issue", "create", "--repo", repo, "--title", title,
                   "--body", child_body(ms, issue), "--milestone", ms["title"]]
            for lab in labels_for(issue):
                cmd += ["--label", lab]
            url = gh(cmd, dry)
            ref = "#" + url.rsplit("/", 1)[-1] if url else "#?"
            children.append((issue, ref))
            if url:
                existing_issues[title] = int(ref[1:])

        tracking_title = f"[{ms['key']}] {ms['title'].split(' — ', 1)[1]}"
        print(f"  tracking: {tracking_title}")
        if tracking_title in existing_issues:
            print("    exists, skipping (edit its checklist manually if children changed)")
            continue
        gh(["issue", "create", "--repo", repo, "--title", tracking_title,
            "--body", tracking_body(ms, children), "--milestone", ms["title"],
            "--label", "tracking"], dry)

    print("\nDone." + (" (dry run, nothing was created)" if dry else ""))


if __name__ == "__main__":
    main()
