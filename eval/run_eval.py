"""
MediScan AI — validation harness
================================
Runs your own set of cases with known answers through exactly the same code the
app uses, and scores the results. Use it to compare models, image-detail
settings, or prompt changes on evidence instead of impressions.

Usage (from the repo root, with GEMINI_API_KEY in .env or the environment):

    python eval/run_eval.py                                  # default model
    python eval/run_eval.py --model gemini-3.5-flash
    python eval/run_eval.py --model gemini-3.6-flash --two-pass
    python eval/run_eval.py --limit 5                        # quick smoke test

Cases file: eval/cases.csv (see eval/cases_template.csv). Columns:
    case_id        short unique id
    files          image file name(s) in eval/cases/, separated by ';'
    modality       one of the app's modality names, or 'Auto-detect'
    history        optional clinical history
    expected_dx    accepted names for the correct diagnosis, separated by '|'
                   (any one matching counts), e.g. "pneumothorax|PTX"
    expected_urgency  Routine / Semi-urgent / Urgent / Emergency (optional)
    critical       yes / no — should a critical finding be flagged? (optional)

Scores reported:
    top-1          correct diagnosis is the leading differential
    top-3          correct diagnosis is in the first three differentials
    urgency exact  urgency level matches
    under-triage   model urgency LOWER than expected (the dangerous error)
    critical recall  critical cases where a critical finding was flagged

Results go to eval/results/<timestamp>_<model>.csv plus a summary on screen.
Keep real patient images out of the public repo — eval/cases/ is git-ignored.

© 2026 Dr. Shantanu Samanta
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

import mediscan_core as core  # noqa: E402

URG_RANK = {u: i for i, u in enumerate(core.URGENCY_LEVELS)}


def matches(dx: str, accepted: list[str]) -> bool:
    d = (dx or "").lower()
    return any(a.strip().lower() and a.strip().lower() in d for a in accepted)


def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=core.DEFAULT_MODELS[0])
    ap.add_argument("--cases", default=str(ROOT / "eval" / "cases.csv"))
    ap.add_argument("--images", default=str(ROOT / "eval" / "cases"))
    ap.add_argument("--resolution", default="MEDIA_RESOLUTION_HIGH")
    ap.add_argument("--two-pass", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between cases (rate limits)")
    args = ap.parse_args()

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not set (put it in .env).")
    if not Path(args.cases).exists():
        sys.exit(f"No cases file at {args.cases}. Copy eval/cases_template.csv to eval/cases.csv.")

    with open(args.cases, newline="", encoding="utf-8") as f:
        cases = [r for r in csv.DictReader(f) if r.get("case_id", "").strip()]
    if args.limit:
        cases = cases[: args.limit]

    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{datetime.now():%Y%m%d_%H%M}_{args.model}{'_2pass' if args.two_pass else ''}.csv"

    rows, t0 = [], time.time()
    for n, c in enumerate(cases, 1):
        cid = c["case_id"].strip()
        try:
            images = []
            for fn in [x.strip() for x in c.get("files", "").split(";") if x.strip()]:
                images.append(core.prepare_image((Path(args.images) / fn).read_bytes(), fn))
            res = core.analyse(args.model, key, images, c.get("history", ""),
                               c.get("modality") or "Auto-detect", args.resolution, args.two_pass)
            rep = res["report"]
            diffs = [d.get("diagnosis", "") for d in rep.get("differentials", [])
                     if d.get("likelihood") != "Must exclude"]
            accepted = [a for a in c.get("expected_dx", "").split("|") if a.strip()]
            top1 = bool(diffs) and matches(diffs[0], accepted)
            top3 = any(matches(d, accepted) for d in diffs[:3])
            urg = core.urgency_of(rep)
            exp_urg = core.normalise_enum(c.get("expected_urgency", ""), core.URGENCY_LEVELS, "")
            crit_flag = bool(rep.get("critical_findings"))
            row = {
                "case_id": cid, "ok": True, "top1": top1, "top3": top3,
                "model_top_dx": diffs[0] if diffs else "", "expected_dx": c.get("expected_dx", ""),
                "model_urgency": urg, "expected_urgency": exp_urg,
                "urgency_exact": (urg == exp_urg) if exp_urg else "",
                "under_triage": (URG_RANK.get(urg, -1) < URG_RANK[exp_urg]) if exp_urg else "",
                "critical_expected": c.get("critical", "").strip().lower(),
                "critical_flagged": crit_flag,
                "confidence": core.confidence_of(rep), "warnings": " | ".join(res["warnings"]),
                "error": "",
            }
        except Exception as exc:
            row = {"case_id": cid, "ok": False, "error": str(exc)[:300]}
        rows.append(row)
        status = "ERR" if not row["ok"] else ("✓" if row.get("top1") else ("~" if row.get("top3") else "✗"))
        print(f"[{n}/{len(cases)}] {cid:<16} {status}  {row.get('model_top_dx', row.get('error', ''))[:70]}")
        time.sleep(args.pause)

    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["ok"]]
    pct = lambda xs: f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "—"  # noqa: E731
    urg_rows = [r for r in ok if r["expected_urgency"]]
    crit_rows = [r for r in ok if r["critical_expected"] == "yes"]
    print("\n" + "=" * 60)
    print(f"Model {args.model} · {'two-pass' if args.two_pass else 'single'} · {args.resolution}")
    print(f"Cases run: {len(ok)}/{len(rows)}  ({time.time() - t0:.0f} s)")
    print(f"Top-1 diagnosis:   {pct([r['top1'] for r in ok])}")
    print(f"Top-3 diagnosis:   {pct([r['top3'] for r in ok])}")
    print(f"Urgency exact:     {pct([r['urgency_exact'] for r in urg_rows])}")
    print(f"Under-triage:      {pct([r['under_triage'] for r in urg_rows])}   <- keep this near 0")
    print(f"Critical recall:   {pct([r['critical_flagged'] for r in crit_rows])}")
    print(f"Results: {out_path}")
    print("Small sets give wide error bars — 30+ cases per modality before drawing conclusions.")


if __name__ == "__main__":
    main()
