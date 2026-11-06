#!/usr/bin/env bash
# Thin wrapper: jarvis inject (Mark XXVII) - forwards all arguments.
# Examples:
#   ./scripts/inject.sh scan
#   ./scripts/inject.sh install --target 192.168.1.50 --os linux --dry-run
#   ./scripts/inject.sh bundle --out umbra-inject-bundle.zip
exec python -m jarvis inject "$@"
