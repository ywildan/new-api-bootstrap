#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/common.sh
source "$SCRIPT_DIR/scripts/common.sh"

main() {
    echo
    echo "New API Bootstrap - Update"
    echo "========================================================================"

    check_dependencies
    load_env
    validate_config

    "$SCRIPT_DIR/scripts/install_new_api.sh"

    echo
    log "Checking New API connection..."

    api_request "GET" "/api/channel/" >/dev/null
    success "New API connection successful."

    echo
    log "Synchronizing channels..."

    "$SCRIPT_DIR/scripts/sync_channels.sh" --apply

    echo
    success "Update completed."
}

main "$@"
