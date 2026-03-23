#!/usr/bin/env bash
# Install the latest VS Code Insiders RPM for Dudley-flavored images.
set -euo pipefail

readonly FORCE_REFRESH="${VSCODE_FORCE_REFRESH:-0}"
readonly CDN_URL="https://update.code.visualstudio.com/latest/linux-rpm-x64/insider"
readonly RPM_PATH="/tmp/code-insiders-latest.rpm"

log() {
    echo "[dudley-vscode-insiders] $*"
}

if [[ "${FORCE_REFRESH}" != "1" ]] && rpm -q code-insiders >/dev/null 2>&1; then
    log "VS Code Insiders already installed; skipping"
    exit 0
fi

log "Downloading latest VS Code Insiders RPM from Microsoft CDN"
curl -fsSL -o "${RPM_PATH}" "${CDN_URL}"

if rpm -q code-insiders >/dev/null 2>&1; then
    log "Installed version: $(rpm -q --queryformat '%{VERSION}-%{RELEASE}' code-insiders)"
fi

log "CDN RPM version: $(rpm -qp --queryformat '%{VERSION}-%{RELEASE}' "${RPM_PATH}")"
log "Installing VS Code Insiders"

if ! dnf5 install -y --allowerasing "${RPM_PATH}" 2>/dev/null; then
    dnf install -y --allowerasing "${RPM_PATH}"
fi

rm -f "${RPM_PATH}"
log "VS Code Insiders installed successfully"
