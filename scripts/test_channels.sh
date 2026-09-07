#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

main() {
    load_env
    check_dependencies
    validate_config

    log "Checking New API connection..."

    api_request "GET" "/api/channel/" >/dev/null
    success "New API connection successful."

    echo
    log "Checking channel synchronization state..."

    "$SCRIPT_DIR/sync_channels.sh"

    echo
    success "Channel check completed."
}

main "$@"
