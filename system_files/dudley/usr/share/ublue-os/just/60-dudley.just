# Dudley runtime commands
#
# One entrypoint for Homebrew bundles and VS Code extensions.
#
# Examples:
#   ujust dudley
#   ujust dudley brew dev
#   ujust dudley extensions
#   ujust dudley extensions force

# ujust dudley list
dudley action="setup" target="all" mode="":
    #!/usr/bin/env bash
    set -euo pipefail

    ACTION="{{ action }}"
    TARGET="{{ target }}"
    MODE="{{ mode }}"
    BREW_DIR="/usr/share/ublue-os/homebrew"
    EXTENSIONS_HOOK="/usr/share/ublue-os/user-setup.hooks.d/20-dudley-vscode-extensions.sh"

    ensure_brew() {
        if ! command -v brew >/dev/null 2>&1; then
            echo "ERROR: Homebrew is not available on PATH"
            exit 1
        fi
    }

    run_bundle() {
        local bundle="$1"
        local brewfile="$BREW_DIR/$bundle"

        ensure_brew
        if [[ ! -f "$brewfile" ]]; then
            echo "ERROR: $brewfile not found"
            exit 1
        fi

        echo "Installing $(basename "$bundle" .Brewfile) ..."
        brew bundle --file="$brewfile"
        install_linux_casks "$brewfile"
        echo "OK: $(basename "$bundle" .Brewfile) complete"
    }

    install_linux_casks() {
        local brewfile="$1"
        local cask

        if [[ "$(uname -s)" != "Linux" ]]; then
            return 0
        fi

        while IFS= read -r cask; do
            [[ -n "$cask" ]] || continue

            if brew list --cask "$cask" >/dev/null 2>&1; then
                echo "OK: $cask already installed"
                continue
            fi

            echo "Installing Linux cask $cask ..."
            brew install --cask "$cask"
        done < <(sed -nE 's/^[[:space:]]*cask[[:space:]]+"([^"]+)".*/\1/p' "$brewfile")
    }

    run_extensions() {
        if [[ ! -x "$EXTENSIONS_HOOK" ]]; then
            echo "ERROR: $EXTENSIONS_HOOK not found"
            exit 1
        fi

        if [[ "$MODE" == "force" ]]; then
            echo "Forcing VS Code extension reinstall..."
            VSCODE_EXTENSIONS_FORCE=1 bash "$EXTENSIONS_HOOK"
        else
            bash "$EXTENSIONS_HOOK"
        fi
    }

    show_list() {
        echo "Available Dudley Brewfiles:"
        if [[ -d "$BREW_DIR" ]]; then
            ls -1 "$BREW_DIR"/dudley-*.Brewfile 2>/dev/null || echo "No Brewfiles found"
        else
            echo "Homebrew directory not found"
        fi

        echo ""
        echo "Examples:"
        echo "  ujust dudley                 # install all Brewfiles, then VS Code extensions"
        echo "  ujust dudley brew dev        # install dev Brewfile only"
        echo "  ujust dudley extensions      # install/update VS Code extensions"
        echo "  ujust dudley extensions force"
    }

    case "$ACTION" in
        setup)
            case "$TARGET" in
                all)
                    run_bundle "dudley-cli.Brewfile"
                    run_bundle "dudley-dev.Brewfile"
                    run_bundle "dudley-fonts.Brewfile"
                    run_bundle "dudley-k8s.Brewfile"
                    run_extensions
                    ;;
                cli)
                    run_bundle "dudley-cli.Brewfile"
                    ;;
                dev)
                    run_bundle "dudley-dev.Brewfile"
                    run_extensions
                    ;;
                fonts)
                    run_bundle "dudley-fonts.Brewfile"
                    ;;
                k8s)
                    run_bundle "dudley-k8s.Brewfile"
                    ;;
                *)
                    echo "ERROR: Unknown setup target '$TARGET'"
                    exit 1
                    ;;
            esac
            ;;
        brew)
            case "$TARGET" in
                all)
                    run_bundle "dudley-cli.Brewfile"
                    run_bundle "dudley-dev.Brewfile"
                    run_bundle "dudley-fonts.Brewfile"
                    run_bundle "dudley-k8s.Brewfile"
                    ;;
                cli)
                    run_bundle "dudley-cli.Brewfile"
                    ;;
                dev)
                    run_bundle "dudley-dev.Brewfile"
                    ;;
                fonts)
                    run_bundle "dudley-fonts.Brewfile"
                    ;;
                k8s)
                    run_bundle "dudley-k8s.Brewfile"
                    ;;
                *)
                    echo "ERROR: Unknown brew target '$TARGET'"
                    exit 1
                    ;;
            esac
            ;;
        extensions)
            run_extensions
            ;;
        list|help|--help|-h)
            show_list
            ;;
        *)
            echo "ERROR: Unknown Dudley action '$ACTION'"
            show_list
            exit 1
            ;;
    esac

# Backward-compatible wrappers for the older split Dudley recipes.
[group('Dudley')]
dudley-brews-cli:
    @ujust dudley brew cli

[group('Dudley')]
dudley-brews-dev:
    @ujust dudley brew dev

[group('Dudley')]
dudley-brews-fonts:
    @ujust dudley brew fonts

[group('Dudley')]
dudley-brews-k8s:
    @ujust dudley brew k8s

[group('Dudley')]
dudley-brews-all:
    @ujust dudley brew all

[group('Dudley')]
dudley-brews-list:
    @ujust dudley list

[group('Dudley')]
dudley-vscode-insiders:
    @ujust dudley brew dev

[group('Dudley')]
dudley-vscode-extensions:
    @ujust dudley extensions

[group('Dudley')]
dudley-vscode-all:
    @ujust dudley setup dev

[group('Dudley')]
dudley-build-info:
    #!/usr/bin/bash
    set -euo pipefail
    /usr/bin/dudley-build-info

# Dudley already inherits from a DX base image, so Bluefin's generic devmode
# rebase recipe should not synthesize a sibling image name for this repo.
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
        if gum confirm "Install the default development Flatpaks?"; then
            ADD_DEVMODE=1 ujust install-system-flatpaks 0 1
        fi
        if gum confirm "Install extra monospace fonts?"; then
            brew bundle install --file=/usr/share/ublue-os/homebrew/dudley-fonts.Brewfile
        fi
        echo "Use ujust dx-group to add your user to the correct groups and complete the installation after rebooting into the development image"
        exit 0
    fi

    echo "Dudley is not built from a DX base image."
    echo "Rebuild with BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx:stable instead of using Bluefin's generic devmode rebase."
    exit 1
