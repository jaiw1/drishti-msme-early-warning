"""Focused experiments the 2026-09-21 review asked for, run OFF the frozen artefact.

These are not pre-registered criteria and they do not grade anything. `validation/run.py`
and `criteria.yaml` remain the acceptance contract; nothing in here can change a verdict,
and no band in `criteria.yaml` is read or written by this package.

What it is for: the review's four disclosed failures, the calibration of the score that is
actually served, and the behaviour of the shipped model under generator regimes it was
never fitted to. Each of those is a question about ONE model — the one the export shipped —
so each answer has to come from that same model rather than from a fresh fit that happens
to use the same hyperparameters. `artefact.py` is what makes that possible: it trains once,
persists the booster, the feature schema and the calibrator together, and every experiment
loads that artefact and only SCORES.

Outputs land in `validation/report/experiments/`, one directory per experiment, each with
its own `result.json` and a short `REPORT.md`. They are committed, because an experiment
nobody can read is not evidence.
"""
