# Contributing Guide

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Verification Checklist (Before Opening a PR)

Run all SDLC quality gates locally:

```bash
ruff check qwm tests scripts
ruff check --select S qwm
pytest --cov=qwm --cov-fail-under=85 -q
python -m pip wheel . --no-deps -w /tmp/qwm-dist
QUICK=1 OFFLINE=1 bash scripts/reproduce_all.sh
```

## Conventions

- Target Python `>=3.10` (tested on `3.10`, `3.12`, and `3.13`).
- Keep changes backward-compatible across `v1` base paper circuits, `v2` Lean/keyed recovery, and `v3` Shallow CLA / NEQR superposition / OPAP / `descriptors_v2`.
- Add unit tests under [tests/](tests/) and update [CHANGELOG.md](CHANGELOG.md) for user-facing changes.
