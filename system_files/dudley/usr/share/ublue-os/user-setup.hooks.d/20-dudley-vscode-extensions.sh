#!/usr/bin/env bash
# VS Code extensions user hook
set -euo pipefail

hook_version="2026-05-26"

resolve_vscode_cli() {
    local brew_prefix=""
    if command -v brew >/dev/null 2>&1; then
        brew_prefix="$(brew --prefix 2>/dev/null || true)"
    fi

    local candidates=()
    if [[ -n "$brew_prefix" ]]; then
        candidates+=("$brew_prefix/bin/code-insiders" "$brew_prefix/bin/code")
    fi
    candidates+=("code-insiders" "code")

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi

        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done

    return 1
}

VSCODE_CMD="$(resolve_vscode_cli || true)"
if [[ -z "$VSCODE_CMD" ]]; then
    echo "Dudley Hook: vscode-extensions skipped because no VS Code CLI is installed yet"
    exit 0
fi

if [[ -r /usr/lib/ublue/setup-services/libsetup.sh ]]; then
    # shellcheck source=/dev/null
    source /usr/lib/ublue/setup-services/libsetup.sh
    if [[ "${VSCODE_EXTENSIONS_FORCE:-0}" != "1" ]] && [[ "$(version-script vscode-extensions "${hook_version}")" == "skip" ]]; then
        echo "Dudley Hook: vscode-extensions already at version ${hook_version}, skipping"
        exit 0
    fi
fi

echo "Dudley Hook: vscode-extensions starting (version ${hook_version})"

USER_DATA_DIR="$HOME/.config/Code - Insiders"
SKEL_SETTINGS="/etc/skel/.config/Code - Insiders/User/settings.json"
if [[ "$(basename "$VSCODE_CMD")" == "code" ]]; then
    USER_DATA_DIR="$HOME/.config/Code"
    SKEL_SETTINGS="/etc/skel/.config/Code/User/settings.json"
fi
mkdir -p "$USER_DATA_DIR/User"
if [[ ! -f "$USER_DATA_DIR/User/settings.json" && -f "$SKEL_SETTINGS" ]]; then
    cp -f "$SKEL_SETTINGS" "$USER_DATA_DIR/User/settings.json"
fi

MARKER="$USER_DATA_DIR/.extensions-installed"
if [[ "${VSCODE_EXTENSIONS_FORCE:-0}" == "1" ]]; then
    echo "Force flag set, will reinstall extensions"
    rm -f "$MARKER" || true

    SETUP_FILE="$HOME/.local/share/ublue/setup_versioning.json"
    if [[ -f "$SETUP_FILE" ]]; then
        TEMP_FILE="$(mktemp)"
        jq 'del(.version.user."vscode-extensions")' "$SETUP_FILE" > "$TEMP_FILE" && mv "$TEMP_FILE" "$SETUP_FILE"
    fi
fi

EXTENSIONS_LIST="/usr/share/ublue-os/vscode-extensions.list"
if [[ ! -f "$EXTENSIONS_LIST" ]]; then
    echo "ERROR: $EXTENSIONS_LIST not found"
    exit 1
fi

echo "Installing VS Code extensions with $(basename "$VSCODE_CMD")..."

while IFS= read -r extension || [[ -n "$extension" ]]; do
    [[ -z "$extension" || "$extension" =~ ^[[:space:]]*# ]] && continue
    extension="$(echo "$extension" | xargs)"
    [[ -z "$extension" ]] && continue

    echo "Installing/updating extension: $extension"
    "$VSCODE_CMD" --install-extension "$extension" --force --user-data-dir "$USER_DATA_DIR" --no-sandbox || \
        echo "Failed to install VS Code extension: $extension" >&2
done < "$EXTENSIONS_LIST"

cat >"$MARKER" <<MARKER_CONTENT
# VS Code extensions installed
# VERSION=${hook_version}
# Date: $(date -Iseconds)
# CLI=${VSCODE_CMD}
MARKER_CONTENT

echo "Dudley Hook: vscode-extensions completed successfully"
