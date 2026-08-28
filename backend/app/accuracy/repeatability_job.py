"""
Automated repeatability job (README §35 Phase 10 / §36 "Repeatability is
measured", Definition-of-Done follow-up item).

Runs the full pipeline end-to-end -- upload -> reconcile -> results ->
accuracy -- N independent times against `sample_data/` (bank.csv,
processor.csv, erp.csv, answer_key.csv), each time as a brand-new batch, and
checks that:

  1. Every run produces the same *decision set* (same left/right ids, same
     decision, same rule_id, same confidence) -- via
     `app.accuracy.metrics.fingerprint_decision` / `repeatability_rate`.
  2. Every run produces the same control totals / match rate / stage
     breakdown / accuracy numbers.

It writes a JSON report plus a human-readable Markdown before/after table to
`backend/reports/`. "Before" is whatever the previous run of this job
recorded (`repeatability_baseline.json`); "after" is the run just performed.
The baseline is only overwritten when the new run is itself fully
repeatable, so a flaky run never silently becomes the new baseline.

Usage (from `backend/`):

    python -m app.accuracy.repeatability_job
    python -m app.accuracy.repeatability_job --runs 5 --data-dir ../sample_data

By default this uses its own throwaway SQLite file (via DATABASE_URL) so it
never touches a developer's working `reconagent.db`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

THIS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = THIS_DIR.parent.parent
REPORTS_DIR = BACKEND_DIR / "reports"
DEFAULT_DATA_DIR = BACKEND_DIR.parent / "sample_data"


def _isolated_database_url() -> str:
    fd, path = tempfile.mkstemp(prefix="reconagent_repeatability_", suffix=".db")
    os.close(fd)
    return f"sqlite:///{path}"


def _run_once(client, data_dir: Path) -> Dict[str, Any]:
    """Upload + reconcile once; return everything needed for comparison."""
    files = {
        "bank_file": ("bank.csv", (data_dir / "bank.csv").read_bytes(), "text/csv"),
        "processor_file": ("processor.csv", (data_dir / "processor.csv").read_bytes(), "text/csv"),
        "erp_file": ("erp.csv", (data_dir / "erp.csv").read_bytes(), "text/csv"),
    }
    answer_key_path = data_dir / "answer_key.csv"
    if answer_key_path.exists():
        files["answer_key_file"] = ("answer_key.csv", answer_key_path.read_bytes(), "text/csv")

    upload_resp = client.post("/api/upload", files=files)
    upload_resp.raise_for_status()
    batch_id = upload_resp.json()["batch_id"]

    reconcile_resp = client.post(f"/api/reconcile/{batch_id}")
    reconcile_resp.raise_for_status()
    reconcile = reconcile_resp.json()

    results_resp = client.get(f"/api/results/{batch_id}")
    results_resp.raise_for_status()
    matches = results_resp.json()["matches"]

    accuracy_resp = client.get(f"/api/accuracy/{batch_id}")
    accuracy_resp.raise_for_status()
    accuracy = accuracy_resp.json()

    return {
        "batch_id": batch_id,
        "match_rate": reconcile["match_rate"],
        "exception_count": reconcile["exception_count"],
        "stage_breakdown": reconcile["stage_breakdown"],
        "validation_status": reconcile.get("validation_status"),
        "control_totals": reconcile.get("control_totals"),
        "invalid_count": reconcile.get("invalid_count"),
        "llm_call_count": reconcile.get("llm_call_count"),
        "llm_batched_call_count": reconcile.get("llm_batched_call_count"),
        "failover_count": reconcile.get("failover_count"),
        "pipeline_version": reconcile.get("pipeline_version"),
        "rule_set_version": reconcile.get("rule_set_version"),
        "normalization_version": reconcile.get("normalization_version"),
        "accuracy": {
            "overall_precision": accuracy.get("overall_precision"),
            "overall_recall": accuracy.get("overall_recall"),
            "overall_f1": accuracy.get("overall_f1"),
            "false_match_rate": accuracy.get("false_match_rate"),
            "missed_match_rate": accuracy.get("missed_match_rate"),
        },
        "decisions": [
            {
                "left_txn_ids": m["left_txn_ids"],
                "right_txn_ids": m["right_txn_ids"],
                "decision": m.get("decision") or m.get("status"),
                "exception_category": m.get("exception_category") or m.get("exception_type"),
                "rule_id": m.get("rule_id"),
                "confidence": m.get("confidence"),
            }
            for m in matches
        ],
    }


def run_job(n_runs: int = 5, data_dir: Path = DEFAULT_DATA_DIR, database_url: str | None = None) -> Dict[str, Any]:
    os.environ["DATABASE_URL"] = database_url or _isolated_database_url()

    # Imported lazily, after DATABASE_URL is set, so app.db builds its engine
    # against the isolated file rather than a developer's working DB.
    from fastapi.testclient import TestClient
    from app.db import init_db
    from app.main import app
    from app.accuracy.metrics import fingerprint_decision, repeatability_rate

    init_db()
    client = TestClient(app)

    runs = [_run_once(client, data_dir) for _ in range(n_runs)]

    baseline_run = runs[0]
    baseline_fp = set(fingerprint_decision(d) for d in baseline_run["decisions"])
    pairwise_rates = []
    identical_metrics = True
    for other in runs[1:]:
        rate = repeatability_rate(baseline_run["decisions"], other["decisions"])
        pairwise_rates.append(rate)
        if rate < 1.0:
            identical_metrics = False
        for key in ("match_rate", "exception_count", "stage_breakdown", "validation_status",
                    "control_totals", "invalid_count", "accuracy"):
            if other[key] != baseline_run[key]:
                identical_metrics = False

    min_repeatability_rate = min(pairwise_rates) if pairwise_rates else 1.0

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_runs": n_runs,
        "data_dir": str(data_dir),
        "pipeline_version": baseline_run["pipeline_version"],
        "rule_set_version": baseline_run["rule_set_version"],
        "normalization_version": baseline_run["normalization_version"],
        "fully_repeatable": identical_metrics,
        "min_repeatability_rate": min_repeatability_rate,
        "per_run": [
            {
                "run_index": i,
                "batch_id": r["batch_id"],
                "match_rate": r["match_rate"],
                "exception_count": r["exception_count"],
                "invalid_count": r["invalid_count"],
                "validation_status": r["validation_status"],
                "llm_call_count": r["llm_call_count"],
                "failover_count": r["failover_count"],
                "accuracy": r["accuracy"],
            }
            for i, r in enumerate(runs)
        ],
    }
    return report


def _load_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _render_markdown(report: Dict[str, Any], baseline: Dict[str, Any] | None) -> str:
    lines = [
        "# Repeatability job report",
        "",
        f"Generated: {report['generated_at']}",
        f"Runs: {report['n_runs']}  |  Pipeline: {report['pipeline_version']}  |  "
        f"Rules: {report['rule_set_version']}  |  Normalization: {report['normalization_version']}",
        f"Fully repeatable across all runs: **{report['fully_repeatable']}**  "
        f"(min pairwise repeatability rate: {report['min_repeatability_rate']})",
        "",
        "## Per-run summary (this execution)",
        "",
        "| Run | Batch | Match rate | Exceptions | Invalid | Validation | LLM calls | Failovers | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["per_run"]:
        acc = r["accuracy"]
        lines.append(
            f"| {r['run_index']} | {r['batch_id']} | {_fmt(r['match_rate'])} | {r['exception_count']} | "
            f"{r['invalid_count']} | {r['validation_status']} | {r['llm_call_count']} | {r['failover_count']} | "
            f"{_fmt(acc['overall_precision'])} | {_fmt(acc['overall_recall'])} | {_fmt(acc['overall_f1'])} |"
        )

    lines += ["", "## Before vs. after", ""]
    if baseline is None:
        lines.append("No prior baseline found -- this run becomes the baseline (if fully repeatable).")
    else:
        b0, r0 = baseline["per_run"][0], report["per_run"][0]
        lines += [
            "| Metric | Before (baseline) | After (this run) | Changed |",
            "|---|---|---|---|",
            f"| Match rate | {_fmt(b0['match_rate'])} | {_fmt(r0['match_rate'])} | "
            f"{'yes' if b0['match_rate'] != r0['match_rate'] else 'no'} |",
            f"| Exception count | {b0['exception_count']} | {r0['exception_count']} | "
            f"{'yes' if b0['exception_count'] != r0['exception_count'] else 'no'} |",
            f"| Precision | {_fmt(b0['accuracy']['overall_precision'])} | "
            f"{_fmt(r0['accuracy']['overall_precision'])} | "
            f"{'yes' if b0['accuracy']['overall_precision'] != r0['accuracy']['overall_precision'] else 'no'} |",
            f"| Recall | {_fmt(b0['accuracy']['overall_recall'])} | "
            f"{_fmt(r0['accuracy']['overall_recall'])} | "
            f"{'yes' if b0['accuracy']['overall_recall'] != r0['accuracy']['overall_recall'] else 'no'} |",
            f"| F1 | {_fmt(b0['accuracy']['overall_f1'])} | {_fmt(r0['accuracy']['overall_f1'])} | "
            f"{'yes' if b0['accuracy']['overall_f1'] != r0['accuracy']['overall_f1'] else 'no'} |",
            f"| Fully repeatable | {baseline['fully_repeatable']} | {report['fully_repeatable']} | — |",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--database-url", type=str, default=None)
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = REPORTS_DIR / "repeatability_baseline.json"
    report_path = REPORTS_DIR / "repeatability_report.json"
    md_path = REPORTS_DIR / "repeatability_report.md"

    baseline = _load_json(baseline_path)
    report = run_job(n_runs=args.runs, data_dir=args.data_dir, database_url=args.database_url)

    report_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(_render_markdown(report, baseline))

    if report["fully_repeatable"]:
        baseline_path.write_text(json.dumps(report, indent=2))

    print(f"Wrote {report_path}")
    print(f"Wrote {md_path}")
    print(f"fully_repeatable={report['fully_repeatable']} "
          f"min_repeatability_rate={report['min_repeatability_rate']}")
    return 0 if report["fully_repeatable"] else 1


if __name__ == "__main__":
    sys.exit(main())
