# LumenStage

LumenStage is a dependency-free Python toolkit for planning and operating theatre and performing-arts productions. It combines a JSON-backed catalog, production-domain workflows, an HTTP/WSGI API, a command-line interface, reporting, and deterministic tests.

The project is designed for production managers, stage managers, technical departments, rights teams, and box-office workflows that need clear rules without a database or web-framework dependency.

## Capabilities

- Catalog records for productions, performances, showbooks, cast members, departments, role tracks, rehearsal slots, props, programs, licenses, staging reviews, preview holds, sound cues, and box-office snapshots.
- Resource-aware scheduling with availability windows, capacity checks, turnaround buffers, recurring bookings, conflict discovery, free-time calculation, and utilization reporting.
- Cue-stack execution with standby/GO transitions, dependencies, critical-cue safety arms, auto-follow timing, failure recovery, snapshots, and operator event logs.
- Rights authorization by territory, time window, audience size, exploitation type, and performance allowance, including deterministic royalty calculations.
- Ticket-band inventory, discounts, tax and fee calculations, complimentary tickets, partial refunds, settlements, and tender reconciliation.
- Evidence-backed production-readiness gates with dependencies, waivers, expiry handling, blockers, owners, weighted scores, and decision history.
- Revisioned company call sheets with contacts, acknowledgements, rescheduling, arrival and lateness tracking, dispatch plans, and call waves.
- Safety-incident response with severity SLAs, evidence, corrective-action dependencies, escalation, closure controls, and operational metrics.
- Location-aware stock and serialized assets with reservations, transfers, issues, returns, cycle counts, maintenance, reorder suggestions, and valuation.
- Atomic JSON transactions, optimistic revisions, verified backups, query expressions, and schema migrations.
- Tamper-evident audit trails with recursive secret redaction, hash-chain verification, replay, filtering, summaries, cursor pages, and NDJSON exchange.
- A WSGI API and CLI covering all catalog resource types.

## Requirements

- Python 3.11 or newer; Python 3.12 is used in CI and the supplied container.
- No runtime packages outside the Python standard library.
- Development versions are pinned in `pyproject.toml` and `Dockerfile`.

## Install

Create an isolated environment, install the project, then run the checks:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/ruff format --check src tests
.venv/Scripts/ruff check src tests
.venv/Scripts/python -m pytest -q
```

On Linux or macOS, use `.venv/bin/` instead of `.venv/Scripts/`.

## CLI

Set a data directory explicitly to keep each environment isolated:

```bash
lumenstage --data-dir ./data resources
lumenstage --data-dir ./data catalog productions create "Hamlet" hamlet --tag classic
lumenstage --data-dir ./data catalog productions list --status active
lumenstage --data-dir ./data metrics
lumenstage --data-dir ./data dashboard
```

The `catalog` command supports `list`, `get`, `create`, `update`, `archive`, and `delete`. Run `lumenstage catalog --help` for the exact options.

## API

`lumenstage.api.create_app()` returns a WSGI application. The generic catalog surface is:

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/health` | Store health and collection list |
| `GET` | `/api/resources` | Available resource types and counts |
| `GET` | `/api/{resource}` | Filtered, paginated resource list |
| `POST` | `/api/{resource}` | Create a catalog record |
| `GET` | `/api/{resource}/{id}` | Retrieve one record |
| `PATCH` | `/api/{resource}/{id}` | Update supported record fields |
| `DELETE` | `/api/{resource}/{id}` | Delete one record |

List queries accept `status`, `q`, repeated `tag`, `page`, and `page_size` parameters. The configured maximum page size is always enforced. JSON errors use the appropriate 400, 404, 405, 409, or 422 status.

Example request:

```http
POST /api/productions HTTP/1.1
Content-Type: application/json

{"name":"Hamlet","slug":"hamlet","tags":["classic"]}
```

## Storage

By default, records are stored in `data/store.json`. Writes replace a temporary file atomically, increment a store-wide revision, and remain protected by a re-entrant process lock. The storage package also supports:

- multi-collection transactions;
- compare-and-swap with expected revisions;
- backup verification and restoration;
- typed repository operations;
- composable query predicates; and
- ordered schema migrations.

Keep the data directory on a filesystem that provides atomic file replacement. For multiple writer processes, provide external coordination or adapt the repository interface to a transactional database.

## Domain safety

All timestamps used by scheduling, cues, rights, call sheets, readiness, and auditing must be timezone-aware. Currency calculations use `Decimal`. Domain failures inherit from `LumenStageError`, with specialized validation, not-found, conflict, storage, and workflow exceptions.

Critical technical cues require an explicit safety arm before GO. Readiness waivers for blocking checks require explicit authorization. Audit values matching sensitive field names are redacted before they enter the hash chain.

## Container environment

The root `Dockerfile` installs only pinned test and lint tools on `python:3.12-slim`. The repository is expected at `/app`, matching the task environment and the working directory used by the image.

```bash
docker build -t lumenstage-dev .
docker run --rm -v "$PWD:/app" lumenstage-dev
```

## Development

Keep changes focused and cover observable behavior. Before committing:

```bash
ruff format --check src tests
ruff check src tests
python -m pytest -q
python -m pip wheel . --no-deps --no-build-isolation -w dist
```

CI runs formatting, linting, and the complete test suite on every push and pull request. Source code uses LF line endings through `.gitattributes`.

## License

MIT © redacted-owner
