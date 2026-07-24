#!/usr/bin/env bash
# Apply the selected Dudley theme in the current user's GNOME session.
set -euo pipefail

hook_version="2026-07-24"
theme="wellness-floor"

if [[ -f /etc/dudley/theme-default ]]; then
    theme="$(tr -d '[:space:]' </etc/dudley/theme-default)"
fi

if [[ -r /usr/lib/ublue/setup-services/libsetup.sh ]]; then
    # shellcheck source=/dev/null
    source /usr/lib/ublue/setup-services/libsetup.sh
    if [[ "$(version-script dudley-theme "$hook_version")" == "skip" ]]; then
        echo "Dudley Hook: theme already at version ${hook_version}, skipping"
        exit 0
    fi
fi

echo "Dudley Hook: applying theme ${theme}"
/usr/bin/dudley-theme apply "$theme"
