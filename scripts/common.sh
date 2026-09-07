#!/usr/bin/env bash

set -Eeuo pipefail

# ============================================================
# New API Bootstrap - Common Utilities
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
CHANNELS_FILE="$PROJECT_ROOT/config/channels.json"

log() {
    printf '[INFO] %s\n' "$*"
}

success() {
    printf '[OK] %s\n' "$*"
}

warn() {
    printf '[WARN] %s\n' "$*" >&2
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

load_env() {
    [[ -f "$ENV_FILE" ]] || die ".env not found. Copy .env.example to .env first."

    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a

    : "${NEW_API_BASE_URL:?NEW_API_BASE_URL is not set}"
    : "${NEW_API_ADMIN_TOKEN:?NEW_API_ADMIN_TOKEN is not set}"
    : "${NEW_API_USER_ID:?NEW_API_USER_ID is not set}"

    NEW_API_BASE_URL="${NEW_API_BASE_URL%/}"
}

check_dependencies() {
    local missing=()

    for cmd in curl python3; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done

    if ((${#missing[@]} > 0)); then
        die "Missing dependencies: ${missing[*]}"
    fi
}

validate_config() {
    [[ -f "$CHANNELS_FILE" ]] || die "config/channels.json not found."

    python3 -m json.tool "$CHANNELS_FILE" >/dev/null ||
        die "Invalid config/channels.json"

    success "Channel configuration is valid."
}

api_request() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"

    local args=(
        --silent
        --show-error
        --fail-with-body
        --request "$method"
        --header "Authorization: Bearer $NEW_API_ADMIN_TOKEN"
        --header "New-Api-User: $NEW_API_USER_ID"
        --header "Content-Type: application/json"
    )

    if [[ -n "$data" ]]; then
        args+=(--data "$data")
    fi

    curl "${args[@]}" "${NEW_API_BASE_URL}${endpoint}"
}
