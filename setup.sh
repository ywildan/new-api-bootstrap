#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/common.sh
source "$SCRIPT_DIR/scripts/common.sh"

main() {
    echo
    echo "New API Bootstrap"
    echo "========================================================================"

    check_dependencies

    # Create .env on first run.
    if [[ ! -f "$ENV_FILE" ]]; then
        cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
        success "Created .env from .env.example."
    fi

    # Start New API if necessary.
    "$SCRIPT_DIR/scripts/install_new_api.sh"

    # Load .env without requiring credentials yet.
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a

    echo

    if [[ -z "${NEW_API_ADMIN_TOKEN:-}" || -z "${NEW_API_USER_ID:-}" ]]; then
        warn "New API admin credentials are not configured yet."

        echo
        echo "1. Open http://localhost:3000"
        echo "2. Complete the initial New API admin setup."
        echo "3. Create a System Access Token."
        echo "4. Put the token and your admin user ID in .env:"
        echo
        echo "   NEW_API_ADMIN_TOKEN=..."
        echo "   NEW_API_USER_ID=..."
        echo
        echo "5. Also configure your provider API keys:"
        echo
        echo "   XKIRO_API_KEY=..."
        echo "   UNROUTER_API_KEY=..."
        echo
        echo "Then run ./setup.sh again."
        exit 0
    fi

    # Check provider API keys.
    missing_keys=()

    [[ -n "${XKIRO_API_KEY:-}" ]] ||
        missing_keys+=("XKIRO_API_KEY")

    [[ -n "${UNROUTER_API_KEY:-}" ]] ||
        missing_keys+=("UNROUTER_API_KEY")

    if ((${#missing_keys[@]} > 0)); then
        warn "Provider API keys are not configured:"
        printf '  - %s\n' "${missing_keys[@]}"

        echo
        echo "Fill them in inside:"
        echo "  $ENV_FILE"
        echo
        echo "Then run ./setup.sh again."
        exit 0
    fi

    load_env
    validate_config

    echo
    log "Checking New API connection..."

    api_request "GET" "/api/channel/" >/dev/null
    success "New API connection successful."

    echo
    log "Synchronizing channels..."

    "$SCRIPT_DIR/scripts/sync_channels.sh" --apply

    echo
    success "Bootstrap completed."
}

main "$@"
