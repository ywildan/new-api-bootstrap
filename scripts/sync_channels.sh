#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

main() {
    load_env
    check_dependencies
    validate_config

    log "Starting channel sync..."

    exec python3 "$SCRIPT_DIR/sync_channels.py" "$@"
}

main "$@"
