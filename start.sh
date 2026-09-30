#!/usr/bin/env bash
# Enter the locked Nix environment and launch a mapper from any directory.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

usage() {
    printf '%s\n' \
        'Usage: ./start.sh [gamepad|wheel|flightstick] [application arguments...]' \
        '' \
        'Default: gamepad' \
        'Examples:' \
        '  ./start.sh' \
        '  ./start.sh gamepad -c default-profile.json' \
        '  ./start.sh wheel --degrees 540 --no-wheel' \
        '  ./start.sh flightstick --edit' \
        '' \
        'Requires SteamVR; connects using OpenVR Background mode.' \
        'Use ./start.sh gamepad --help for application options.'
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    gamepad|wheel|flightstick) mode="$1"; shift ;;
    '') mode=gamepad ;;
    -*) mode=gamepad ;;
    *) printf 'Unknown mode: %s\n' "$1" >&2; usage >&2; exit 2 ;;
esac

if ! command -v nix >/dev/null 2>&1; then
    printf 'Error: nix is required. Install Nix with flakes enabled.\n' >&2
    exit 1
fi

# path: includes a newly created/untracked flake.nix. bash -c receives arguments
# separately, never as interpolated shell code. exec preserves signals/exit codes.
exec nix develop "path:$PWD" --command bash -c '
    set -euo pipefail
    setup-python
    exec .venv/bin/python -u "$@"
' fnuipad "vr_${mode}_main.py" "$@"
