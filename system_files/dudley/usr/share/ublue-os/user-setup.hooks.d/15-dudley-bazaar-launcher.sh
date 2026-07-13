#!/usr/bin/env bash

set -euo pipefail

launcher="${HOME}/.local/share/applications/io.github.kolunmi.Bazaar.desktop"

# Older Bluefin RPM builds could leave a per-user launcher that calls the
# removed host binary. It masks the current Flatpak launcher in GNOME's app
# enumeration, so remove only that obsolete form.
if [[ -f "${launcher}" ]] && grep -Eq '^Exec=bazaar([[:space:]]|$)' "${launcher}"; then
    rm -f "${launcher}"
fi
