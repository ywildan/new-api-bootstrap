# AGENTS.md — Project Context for Coding Agents

Read this first. The current source code is authoritative for implementation
details; this file records durable architecture, safety rules, and invariants.

## Project Overview

`new-api-bootstrap` is a reproducible deployment + declarative configuration
for a [New API](https://github.com/QuantumNous/new-api) instance (Docker
Compose, `calciumion/new-api:latest`, port 3000). It solves one problem:
keeping the New API channel list in a reviewable file and synchronizing it
idempotently. It currently manages **channels only** (no combos).

## Architecture

```
scripts/channel_manager.py
        ↓  edits only this file
config/channels.json        ← source of truth for managed channels
        ↓  read by
scripts/sync_channels.py (via scripts/sync_channels.sh wrapper)
        ↓  New API management API (/api/channel/)
    New API instance
```

- `config/channels.json` is the source of truth for managed channel config.
- `scripts/channel_manager.py` is an interactive editor for that file. It
  never talks to New API and never applies/syncs anything.
- `scripts/sync_channels.py` is the sync engine (stdlib `urllib`, no third
  party). `scripts/sync_channels.sh` loads `.env`, checks deps, validates
  JSON syntax, then execs it.
- `scripts/common.sh` holds shared shell helpers (`load_env`,
  `check_dependencies`, `validate_config`, `api_request`).
- `scripts/test_channels.sh` checks the API connection, then runs a dry-run
  sync. `setup.sh` bootstraps Docker + `.env` + admin setup and applies.
  `update.sh` validates, ensures New API runs, and applies.

## Channel Configuration

`config/channels.json` shape: `{"version": 1, "channels": [...]}`.

- **Identity**: `name` is the unique key (non-empty, unique across channels).
- **Managed fields** (compared by the sync engine): `name`, `type` (mapped
  via `TYPE_MAP`, currently only `"openai"` → `1`), `base_url`, `models`
  (order-insensitive — sorted before compare), `group`, `priority`, `weight`,
  `auto_ban`, `model_mapping`, and `test_model` only when present in config.
- **Provider**: `provider` is a local label; connection details come from
  `base_url` + `api_key_env`. `api_key_env` holds an **environment-variable
  name** (e.g. `"XKIRO_API_KEY"`), never a secret value.
- **Secrets resolution**: at apply time `build_payload()` reads the actual
  key from `os.environ[key_env]` and dies if the variable is missing/empty.
- **`model_mapping` is a JSON object** in `channels.json`
  (e.g. `{"coding": "some/model"}`). The sync engine serializes it to a JSON
  string for the API; it must never be stored pre-encoded.
- **Sync behavior**: per channel → `CREATE` (absent in New API),
  `UPDATE` (managed fields differ, diff printed), `SKIP` (matches).
  Creation uses `POST /api/channel/` with `mode: "single"` and
  `groups: [<group>]`; updates use `PUT /api/channel/` with the channel `id`.
- **No deletion**: channels present in New API but absent from the config are
  left untouched. There is no prune mode.

## Channel Manager (`scripts/channel_manager.py`)

Interactive editor for `config/channels.json`. Invariants to preserve:

- Edits the config file only. No API calls, no auto-apply, no deletion of
  channels it doesn't understand; unknown fields on channel objects are
  preserved via in-memory edits (never rebuild objects from a fixed schema).
- **Python standard library only** (no Rich/Textual/prompt_toolkit/curses
  wrappers). Key modules: `termios`/`tty`/`select` for keys, `shutil` for
  terminal size.
- **Safe writes**: load → modify in memory → validate → write temp file in
  the same directory → flush/fsync → atomic `os.replace()`; previous file
  kept at `config/channels.json.bak` (gitignored); no temp files left behind;
  `indent=2, ensure_ascii=False`, trailing newline.
- **Validation** (`validate_config_data`): root object, `version`, channels
  array, unique non-empty names, required `provider`/`type`/`base_url`/
  `api_key_env`, non-empty `models` with no empties/duplicates, non-empty
  `group`, int `priority`, numeric `weight`, bool `auto_ban`,
  object-typed `model_mapping` with non-empty alias/target strings, optional
  non-empty `test_model`. Validation never modifies the file.
- **Two UI modes**: full-screen alternate-screen TUI when stdin **and**
  stdout are TTYs; plain numbered/text fallback otherwise (no ANSI/alt-screen
  sequences when redirected).
- **Terminal lifecycle is centralized** (`terminal_session` context manager,
  `select_menu`, `show_info`, `ask_text`, `confirm_screen`): alt-screen
  `\033[?1049h/l`, cursor hide/show, per-menu raw mode — all restored in
  `try/finally` on Exit, `q`/`Esc`, Ctrl+C, EOF, and exceptions.
- **Keyboard**: arrows move one item; PgUp/PgDn/Home/End in scrollable lists;
  Enter selects; `q`/`Esc` backs out (main menu: `q` quits); raw-mode line
  input is never used, so typing `q` in a text field is safe.
- **Viewport**: full-terminal header/content/footer frame re-queried via
  `shutil.get_terminal_size()` on every render (resize takes effect on next
  redraw); small menus centered; long lists top-anchored with
  selected/scroll-offset/window math, position indicator, scrollbar;
  wrap-around for small menus, bounded navigation for data lists; graceful
  "Terminal too small" below 60×20.
- **ANSI-aware rendering**: SGR sequences have zero visual width
  (`visible_len`); truncation never splits an escape sequence and re-emits a
  reset when cutting styled content; every screen starts from a reset SGR
  state. Selected-row reverse-video must be kept.

## Synchronization Safety

- Dry run is the default (`./scripts/sync_channels.sh`); mutation requires
  explicit `--apply`. `setup.sh`/`update.sh` apply by design — run them only
  when the operator intends to change the live instance.
- Sync is idempotent: a fully synced state reports only `SKIP`.
- Only these operations modify New API: `sync_channels.sh --apply`,
  `setup.sh`, `update.sh`. The Channel Manager never does.
- Safe edit workflow: manager → Validate → `sync_channels.sh` (dry run) →
  review → `--apply` → dry run again (expect all `SKIP`).

## Secrets and Security

- Real credentials live only in `.env` (gitignored). Never commit them;
  never print secret values in logs, diffs, or UI (show only env-var names).
- `config/channels.json` must contain `api_key_env` names, never keys.
- New provider env vars belong in local `.env` and should be documented as
  empty entries in `.env.example` (see README).
- Do not modify credentials unless explicitly requested. Verify with
  `git check-ignore -v .env` before committing.

## Development Workflow

Real commands (do not invent others):

```bash
python -m py_compile scripts/channel_manager.py   # syntax check Python edits
python scripts/channel_manager.py                 # interactive editor (TTY for TUI)
./scripts/sync_channels.sh                        # dry-run preview (needs .env + live API)
./scripts/sync_channels.sh --apply                # mutate live instance (explicit only)
./scripts/test_channels.sh                        # connection check + dry-run state
```

`common.sh :: validate_config` is JSON-syntax only (`python -m json.tool`);
semantic validation lives in the manager (`validate_config_data`) — keep both
passing after config-related changes. The manager resolves `channels.json`
relative to the repo root via `pathlib`, never hardcoded home directories.

## Agent Rules

- Read this file first, then inspect the **current** source before changing
  anything; source is authoritative, this file is invariants.
- Preserve backward compatibility, security/safety invariants, and the
  stdlib-only constraint.
- Make minimal, scoped changes; no unrelated refactors or files.
- Never expose secrets; never auto-run apply/setup/update; never
  commit or push unless explicitly requested.
- Validate before reporting: `py_compile`, non-TTY smoke run, config hash
  unchanged when only behavior (not data) was meant to change.

## Documentation Freshness

Update this file as part of any change that alters architecture, sync
semantics, security assumptions, or the invariants above. Ordinary bug fixes
and small features do not need a changelog here.
