# How we work

## Branches
- `main` is always runnable. Nobody pushes to it directly.
- Branch per task: `part1/simulator-profiles`, `part2/adx-writer`, `part3/grafana-dashboard`, ...
- Open a pull request, get **one approval** from another member, then merge.

## Who owns what
| Folder | Owner |
|---|---|
| `simulator/`, `mosquitto/`, `scripts/` | Part 1 – Mashal |
| `processor/` | Part 2 – Collins |
| `adx/`, `grafana/`, `docker-compose.yml` | Part 3 – Issaq |
| `tests/`, `docs/` | everyone |

## The shared contract
Topic names, JSON payload, ADX tables: see README section 4.
Changing any of these = PR approved by **all three**.

## Before opening a PR
```bash
pip install -r processor/requirements.txt
pytest tests/
docker compose up -d --build   # make sure everything still starts
```

## Secrets
Never commit `.env`, `mosquitto/config/passwd` or anything in `mosquitto/certs/`.
