# Dudley runtime setup
#
#   ujust dudley
#   ujust dudley ai
#   ujust dudley info

[group('Dudley')]
dudley target="":
    #!/usr/bin/env bash
    set -euo pipefail

    TARGET="{{ target }}"
    BREW_DIR="/usr/share/ublue-os/homebrew"
    PROFILE_INFO="/usr/share/dudley/homebrew-profiles.json"
    EXTENSIONS_HOOK="/usr/share/ublue-os/user-setup.hooks.d/20-dudley-vscode-extensions.sh"
    NO_ASK_HELPER="/usr/libexec/dudley/configure-homebrew-no-ask"

    ensure_brew() {
        if ! command -v brew >/dev/null 2>&1; then
            ujust bluefin-cli
        fi
        if ! command -v brew >/dev/null 2>&1; then
            echo "ERROR: Homebrew is not available on PATH"
            exit 1
        fi
    }

    install_linux_casks() {
        local brewfile="$1"
        local cask

        [[ "$(uname -s)" == "Linux" ]] || return 0
        while IFS= read -r cask; do
            [[ -n "$cask" ]] || continue
            brew list --cask "$cask" >/dev/null 2>&1 || brew install --cask "$cask"
        done < <(sed -nE 's/^[[:space:]]*cask[[:space:]]+"([^"]+)".*/\1/p' "$brewfile")
    }

    run_bundle() {
        local bundle="$1"
        local brewfile="$BREW_DIR/$bundle"

        [[ -f "$brewfile" ]] || { echo "ERROR: $brewfile not found"; exit 1; }
        ensure_brew
        "$NO_ASK_HELPER"
        brew bundle --file="$brewfile"
        install_linux_casks "$brewfile"
    }

    case "$TARGET" in
        "")
            run_bundle "dudley-default.Brewfile"
            bash "$EXTENSIONS_HOOK"
            ;;
        ai)
            run_bundle "dudley-ai.Brewfile"
            ;;
        info)
            /usr/bin/dudley-build-info
            echo
            cat "$PROFILE_INFO"
            ;;
        *)
            echo "ERROR: expected: ujust dudley [ai|info]"
            exit 1
            ;;
    esac

# Dudley already inherits from a developer image, so Bluefin's generic devmode
# rebase recipe should not synthesize a sibling image name.
devmode:
    @ujust toggle-devmode

toggle-devmode:
    #!/usr/bin/env bash
    set -euo pipefail

    IMAGE_INFO_FILE="${IMAGE_INFO_FILE:-/usr/share/ublue-os/image-info.json}"
    if [[ ! -f "$IMAGE_INFO_FILE" ]]; then
        echo "ERROR: $IMAGE_INFO_FILE not found"
        exit 1
    fi

    image_flavor="$(jq -r '."image-flavor" // ""' "$IMAGE_INFO_FILE")"
    base_image_name="$(jq -r '."base-image-name" // ""' "$IMAGE_INFO_FILE")"

    if [[ "$image_flavor" =~ dx || "$base_image_name" =~ dx ]]; then
        echo "Dudley is already built from a developer image."
        ujust dudley
        if gum confirm "Install the default development Flatpaks?"; then
            ADD_DEVMODE=1 ujust install-system-flatpaks 0 1
        fi
        echo "Use ujust dx-group when the image provides Docker or virtualization groups."
        exit 0
    fi

    echo "Dudley is not built from a developer base image."
    echo "Install Dudley's portable user-space tools with: ujust dudley"
    exit 1
