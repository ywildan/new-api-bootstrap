#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

main() {
    log "Checking Docker..."

    command -v docker >/dev/null 2>&1 ||
        die "Docker is not installed."

    docker compose version >/dev/null 2>&1 ||
        die "Docker Compose is not available."

    [[ -f "$PROJECT_ROOT/docker-compose.yml" ]] ||
        die "docker-compose.yml not found."

    # If the managed New API container is already running, leave it alone.
    if docker ps \
        --filter "name=^/new-api$" \
        --filter "status=running" \
        --format '{{.Names}}' | grep -qx "new-api"; then

        success "New API is already running."
        return 0
    fi

    log "Starting New API..."

    docker compose \
        -f "$PROJECT_ROOT/docker-compose.yml" \
        up -d

    success "New API container started."
}

main "$@"
