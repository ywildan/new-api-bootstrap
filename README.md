# New API Bootstrap

A simple and reproducible bootstrap configuration for deploying and managing [New API](https://github.com/QuantumNous/new-api) channels.

This project provides Docker Compose deployment and declarative channel synchronization. Channel configurations are stored in JSON while API keys and other secrets remain in a local `.env` file.

## Features

- Docker Compose deployment for New API
- Declarative channel configuration
- Automatic channel creation
- Automatic channel updates
- Idempotent synchronization
- Dry-run by default
- Explicit `--apply` mode
- Pagination support for larger channel lists
- Provider API keys stored outside Git
- Safe synchronization — unmanaged channels are not automatically deleted
- Simple setup and update scripts

> Currently, this project manages **channels only**. Combo synchronization is not included yet.

## Requirements

Before using this project, install:

- Git
- Docker
- Docker Compose
- Python 3
- curl

Docker must be running and accessible by your current user.

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd new-api-bootstrap
```

Run the initial setup:

```bash
./setup.sh
```

On the first run, the script will:

1. Create `.env` from `.env.example` if necessary.
2. Start the New API Docker container.
3. Ask you to complete the New API administrator setup.
4. Wait for the required credentials to be configured.

Open:

```text
http://localhost:3000
```

Complete the New API administrator setup.

## Environment Configuration

Edit:

```bash
nano .env
```

Configure the following values:

```env
# New API
NEW_API_BASE_URL=http://localhost:3000
NEW_API_ADMIN_TOKEN=
NEW_API_USER_ID=

# Providers
XKIRO_API_KEY=
UNROUTER_API_KEY=
```

### New API credentials

`NEW_API_ADMIN_TOKEN` should contain a New API System Access Token.

`NEW_API_USER_ID` should contain the administrator user ID used to authenticate management API requests.

### Provider credentials

Provider API keys are referenced by channel configuration using `api_key_env`.

For example:

```json
"api_key_env": "XKIRO_API_KEY"
```

means the actual API key is read from:

```env
XKIRO_API_KEY=
```

API keys should never be placed directly inside `config/channels.json`.

After configuring `.env`, run:

```bash
./setup.sh
```

again.

## Channel Configuration

Channels are defined in:

```text
config/channels.json
```

Example:

```json
{
  "name": "Example-Channel",
  "provider": "example",
  "type": "openai",
  "base_url": "https://api.example.com",
  "api_key_env": "EXAMPLE_API_KEY",
  "models": [
    "example-model"
  ],
  "group": "default",
  "priority": 0,
  "weight": 0,
  "auto_ban": true
}
```

If you introduce another provider environment variable, also add it to your local `.env` and preferably document the empty variable in `.env.example`.

## Synchronizing Channels

### Dry run

To preview changes without modifying New API:

```bash
./scripts/sync_channels.sh
```

Example:

```text
[SKIP]   Existing-Channel
[UPDATE] Changed-Channel
[CREATE] New-Channel

Create : 1
Update : 1
Skip   : 1
Total  : 3

Dry run only. Use --apply to apply changes.
```

### Apply changes

To synchronize the configuration with New API:

```bash
./scripts/sync_channels.sh --apply
```

The synchronizer compares managed channel fields and performs:

- `CREATE` — channel does not exist
- `UPDATE` — managed configuration differs
- `SKIP` — channel already matches the configuration

Model ordering does not trigger unnecessary updates.

Optional fields such as `test_model` are only managed when explicitly defined in the configuration.

## Updating

After pulling newer repository changes:

```bash
git pull
./update.sh
```

The update script:

1. Validates the environment and channel configuration.
2. Ensures New API is running.
3. Checks the New API connection.
4. Applies channel configuration changes.

## Safety

The synchronizer intentionally does **not** delete channels that are absent from `config/channels.json`.

For example, if New API contains:

```text
Channel-A
Channel-B
Channel-C
```

while the configuration only manages:

```text
Channel-A
Channel-B
```

`Channel-C` will remain untouched.

This prevents accidental deletion of manually managed or unrelated channels.

There is currently no automatic prune/delete mode.

## Secrets

Never commit `.env`.

The repository `.gitignore` excludes:

```text
.env
data/
*.db
*.sqlite
*.sqlite3
__pycache__/
*.pyc
```

Before committing changes, you can verify:

```bash
git check-ignore -v .env
```

Never put API keys, access tokens, passwords, or other credentials inside:

- `README.md`
- `config/channels.json`
- shell scripts
- Python scripts
- committed configuration files

Use environment variables instead.

## Project Structure

```text
new-api-bootstrap/
├── config/
│   └── channels.json
├── scripts/
│   ├── common.sh
│   ├── install_new_api.sh
│   ├── sync_channels.sh
│   ├── sync_channels.py
│   └── test_channels.sh
├── .env.example
├── .gitignore
├── docker-compose.yml
├── README.md
├── setup.sh
└── update.sh
```

### Main files

`setup.sh`
: Initial setup and channel synchronization.

`update.sh`
: Applies configuration updates to an existing installation.

`config/channels.json`
: Declarative channel definitions.

`scripts/sync_channels.py`
: Channel synchronization engine.

`scripts/sync_channels.sh`
: Shell wrapper responsible for loading and validating the environment.

`scripts/install_new_api.sh`
: Starts the New API Docker deployment when necessary.

## Adding a Channel

Add another object to the `channels` array in:

```text
config/channels.json
```

Then preview the change:

```bash
./scripts/sync_channels.sh
```

If the result is correct:

```bash
./scripts/sync_channels.sh --apply
```

Run the dry-run again afterward:

```bash
./scripts/sync_channels.sh
```

A fully synchronized configuration should report only `SKIP` entries.

## License

No license has been specified yet.
