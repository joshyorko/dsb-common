#!/usr/bin/env bash

set -euo pipefail

state_file="${HOME}/.local/state/dudley/desktop-parity-v1"
panel_extension="custom-command-list@storageb.github.com"

if [[ -f "${state_file}" ]]; then
    exit 0
fi

if ! gnome-extensions enable "${panel_extension}"; then
    echo "Dudley Hook: Bluefin top-panel menu is not ready; retrying next login" >&2
    exit 0
fi

migrate_vscode_fonts() {
    local settings_file=$1
    local temporary_file

    [[ -f "${settings_file}" ]] || return 0
    command -v jq >/dev/null 2>&1 || return 0

    temporary_file="$(mktemp)"
    jq "
        if (.[\"editor.fontFamily\"] == \"'monospace'\" or .[\"editor.fontFamily\"] == \"monospace\") then
            .[\"editor.fontFamily\"] = \"'JetBrains Mono', 'Cascadia Code', 'Droid Sans Mono', monospace, 'Symbols Nerd Font Mono'\"
            | if .[\"editor.fontSize\"] == 14 then .[\"editor.fontSize\"] = 16 else . end
        else . end
        | if .[\"terminal.integrated.fontFamily\"] == \"monospace\" then
            .[\"terminal.integrated.fontFamily\"] = \"JetBrains Mono\"
            | if .[\"terminal.integrated.fontSize\"] == 14 then .[\"terminal.integrated.fontSize\"] = 16 else . end
        else . end
    " "${settings_file}" >"${temporary_file}"
    chmod --reference="${settings_file}" "${temporary_file}"
    mv "${temporary_file}" "${settings_file}"
}

migrate_vscode_fonts "${HOME}/.config/Code/User/settings.json"
migrate_vscode_fonts "${HOME}/.config/Code - Insiders/User/settings.json"

install -d "$(dirname "${state_file}")"
touch "${state_file}"
