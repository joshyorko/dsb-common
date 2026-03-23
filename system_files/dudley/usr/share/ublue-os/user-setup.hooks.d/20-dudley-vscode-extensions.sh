#!/usr/bin/env bash
set -euo pipefail

hook_version="2026-03-23"
if [[ -r /usr/lib/ublue/setup-services/libsetup.sh ]]; then
    # shellcheck source=/dev/null
    source /usr/lib/ublue/setup-services/libsetup.sh
    if [[ "$(version-script vscode-extensions "${hook_version}")" == "skip" ]]; then
        exit 0
    fi
fi

command -v code-insiders >/dev/null 2>&1 || exit 0

extensions_list="/usr/share/ublue-os/vscode-extensions.list"
[[ -f "${extensions_list}" ]] || exit 0

mkdir -p "${HOME}/.config" || true
user_data_dir="${HOME}/.config/Code - Insiders"
mkdir -p "${user_data_dir}" || true

marker="${user_data_dir}/.extensions-installed"
if [[ "${VSCODE_EXTENSIONS_FORCE:-0}" == "1" ]]; then
    rm -f "${marker}" || true
fi

while IFS= read -r extension || [[ -n "${extension}" ]]; do
    [[ -z "${extension}" || "${extension}" =~ ^# ]] && continue
    extension="$(echo "${extension}" | xargs)"
    [[ -z "${extension}" ]] && continue

    code-insiders \
        --install-extension "${extension}" \
        --force \
        --user-data-dir "${user_data_dir}" \
        --no-sandbox || \
        echo "Failed to install VS Code Insiders extension: ${extension}" >&2
done < "${extensions_list}"

cat >"${marker}" <<MARKER_CONTENT
# VSCode Insiders extensions installed
# VERSION=${hook_version}
# Date: $(date -Iseconds)
MARKER_CONTENT
