# Jellyfin Torrent Organizer API Skill

Use this guide when another LLM or agent needs to control the organizer service over HTTP.

## Base URL

- Local: `http://127.0.0.1:18327`
- LAN: `http://10.69.1.164:18327`

## Purpose

This service scans configured torrent folders, uses Ollama to classify media, resolves Jellyfin target paths, and then either:

- plans moves in `dryRun` mode, or
- performs real moves when `dryRun` is `false`

Only one run can be active at a time.

## Endpoints

### Health

- `GET /health`

Example:

```bash
curl http://10.69.1.164:18327/health
```

### Start a run

- `POST /runs`

Request body:

```json
{
  "dryRun": true,
  "replaceExisting": true
}
```

Notes:

- `dryRun: true` means plan only, do not move files.
- `dryRun: false` means execute real moves.
- `replaceExisting: true` allows replacing an existing target file.
- If another run is already active, the API returns `409`.

Examples:

```bash
curl -X POST http://10.69.1.164:18327/runs \
  -H 'Content-Type: application/json' \
  -d '{"dryRun":true,"replaceExisting":true}'
```

```bash
curl -X POST http://10.69.1.164:18327/runs \
  -H 'Content-Type: application/json' \
  -d '{"dryRun":false,"replaceExisting":true}'
```

### Get current run summary

- `GET /runs/current`

Use this to check live progress or latest run state.

`GET /runs/current` now includes live fields while a run is active:

- `active_step`
- `active_item_path`
- `ai_output`
- `logs`

Example:

```bash
curl http://10.69.1.164:18327/runs/current
```

Response fields include:

- `run_id`
- `status`: `queued`, `running`, `completed`, `failed`, `cancelled`
- `counts.scanned`
- `counts.classified`
- `counts.moved`
- `counts.replaced`
- `counts.skipped`
- `counts.failed`
- `summary_path`
- `log_path`

### Get current run logs

- `GET /runs/current/logs`

Example:

```bash
curl http://10.69.1.164:18327/runs/current/logs
```

### Stream raw AI output

- `GET /runs/current/ai`

This is a plain text streaming endpoint. It prints the live Ollama output as it is generated.

Example:

```bash
curl -N http://10.69.1.164:18327/runs/current/ai
```

The stream includes small separator headers when the run, item, or AI step changes.

### Stream live logs and AI output

- `GET /logs`

This is an SSE endpoint. It streams the full current run snapshot whenever anything changes.

Example:

```bash
curl -N http://10.69.1.164:18327/logs
```

Each SSE message uses:

- event: `current`
- data: full JSON for the current run, including `ai_output` and `logs`

### Get a specific run summary

- `GET /runs/{run_id}`

Example:

```bash
curl http://10.69.1.164:18327/runs/<run_id>
```

### Get a specific run logs

- `GET /runs/{run_id}/logs`

Example:

```bash
curl http://10.69.1.164:18327/runs/<run_id>/logs
```

## Recommended LLM Workflow

### Safe mode

1. Call `POST /runs` with `{"dryRun": true}`.
2. Poll `GET /runs/current` until `status` is `completed` or `failed`.
3. Read `GET /runs/current/logs`.
4. Summarize what would move, what would be skipped, and any suspicious path choices.

### Real move mode

1. First do a dry run.
2. Inspect the logs for bad movie/series classification, wrong season/episode extraction, or ugly target paths.
3. Only then call `POST /runs` with `{"dryRun": false}`.
4. Poll `GET /runs/current` until finished.
5. Read `GET /runs/current/logs` and report the final moved paths.

## How to Interpret Logs

Each log entry has:

- `timestamp`
- `level`
- `event`
- `message`
- `item_path`
- `details`

Common events:

- `scan.started`
- `candidate.classified`
- `candidate.skipped`
- `target.resolved`
- `action.planned`
- `candidate.failed`

Important interpretation rules:

- `candidate.classified` tells you whether the item was treated as `movie`, `series`, or `skip`.
- `target.resolved` contains the chosen `target_dir` and `target_path`.
- `action.planned` is emitted for both dry runs and real runs; check `details.dryRun`.
- `candidate.failed` means the item was not processed successfully.

## LLM Behavior Guidance

When using this API, the LLM should:

- prefer dry run first
- warn before using `dryRun: false`
- mention the exact target paths from the logs
- mention classification confidence when it looks weak
- call out suspicious season/episode guesses
- call out ugly existing folder matches that may hurt Jellyfin naming

## Quick Links

- Health: `http://10.69.1.164:18327/health`
- Current summary: `http://10.69.1.164:18327/runs/current`
- Current logs: `http://10.69.1.164:18327/runs/current/logs`
