"""
End-to-end repeatability check (README §36 "Repeatability is measured").

Runs the full upload -> reconcile -> results -> accuracy pipeline against
`sample_data/` a handful of times, in-process, against an isolated SQLite
file, and asserts every run produced the identical decision set and
identical headline metrics. The full 5-run job with report generation is
`app.accuracy.repeatability_job` (run via
`python -m app.accuracy.repeatability_job` -- kept out of the default test
run since it also writes report files, but exercised here at a smaller
scale so CI catches any non-determinism regression).
"""
from app.accuracy.repeatability_job import run_job, DEFAULT_DATA_DIR


def test_pipeline_is_repeatable_across_independent_runs(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'repeatability_test.db'}"
    report = run_job(n_runs=3, data_dir=DEFAULT_DATA_DIR, database_url=db_url)

    assert report["n_runs"] == 3
    assert report["fully_repeatable"] is True
    assert report["min_repeatability_rate"] == 1.0
    match_rates = {r["match_rate"] for r in report["per_run"]}
    exception_counts = {r["exception_count"] for r in report["per_run"]}
    assert len(match_rates) == 1
    assert len(exception_counts) == 1
