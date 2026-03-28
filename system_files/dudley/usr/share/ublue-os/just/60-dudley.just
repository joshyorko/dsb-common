# vim: set ft=make :
########################
### Dudley's Brew Installation Commands
########################
## Dudley-opinionated just recipes for installing packages from Brewfiles.
## These are placed in system_files/dudley and apply only to Dudley-flavoured images.

# Install CLI tools and utilities
[group('Dudley')]
dudley-brews-cli:
    #!/usr/bin/bash
    set -euo pipefail
    BREWFILE="/usr/share/ublue-os/homebrew/dudley-cli.Brewfile"
    if [ -f "$BREWFILE" ]; then
        echo "Installing CLI tools from dudley-cli.Brewfile..."
        brew bundle --file="$BREWFILE"
        echo "✓ CLI tools installation complete"
    else
        echo "ERROR: $BREWFILE not found"
        exit 1
    fi

# Install development tools
[group('Dudley')]
dudley-brews-dev:
    #!/usr/bin/bash
    set -euo pipefail
    BREWFILE="/usr/share/ublue-os/homebrew/dudley-dev.Brewfile"
    if [ -f "$BREWFILE" ]; then
        echo "Installing development tools from dudley-dev.Brewfile..."
        brew bundle --file="$BREWFILE"
        echo "✓ Development tools installation complete"
    else
        echo "ERROR: $BREWFILE not found"
        exit 1
    fi

# Install fonts
[group('Dudley')]
dudley-brews-fonts:
    #!/usr/bin/bash
    set -euo pipefail
    BREWFILE="/usr/share/ublue-os/homebrew/dudley-fonts.Brewfile"
    if [ -f "$BREWFILE" ]; then
        echo "Installing fonts from dudley-fonts.Brewfile..."
        brew bundle --file="$BREWFILE"
        echo "✓ Fonts installation complete"
    else
        echo "ERROR: $BREWFILE not found"
        exit 1
    fi

# Install Kubernetes and cloud-native tools
[group('Dudley')]
dudley-brews-k8s:
    #!/usr/bin/bash
    set -euo pipefail
    BREWFILE="/usr/share/ublue-os/homebrew/dudley-k8s.Brewfile"
    if [ -f "$BREWFILE" ]; then
        echo "Installing Kubernetes tools from dudley-k8s.Brewfile..."
        brew bundle --file="$BREWFILE"
        echo "✓ Kubernetes tools installation complete"
    else
        echo "ERROR: $BREWFILE not found"
        exit 1
    fi

# Install all Dudley brew packages
[group('Dudley')]
dudley-brews-all:
    #!/usr/bin/bash
    set -euo pipefail
    echo "Installing all Dudley brew packages..."
    echo ""
    echo "=== Installing CLI tools ==="
    ujust dudley-brews-cli
    echo ""
    echo "=== Installing development tools ==="
    ujust dudley-brews-dev
    echo ""
    echo "=== Installing fonts ==="
    ujust dudley-brews-fonts
    echo ""
    echo "=== Installing Kubernetes tools ==="
    ujust dudley-brews-k8s
    echo ""
    echo "✓ All Dudley brew packages installed!"

# List available Dudley Brewfiles
[group('Dudley')]
dudley-brews-list:
    #!/usr/bin/bash
    set -euo pipefail
    echo "Available Brewfiles in /usr/share/ublue-os/homebrew/:"
    if [ -d "/usr/share/ublue-os/homebrew" ]; then
        ls -1 /usr/share/ublue-os/homebrew/dudley-*.Brewfile 2>/dev/null || echo "No Dudley Brewfiles found"
    else
        echo "Homebrew directory not found"
    fi

# Install VS Code Insiders extensions from list
[group('Dudley')]
dudley-vscode-insiders:
    #!/usr/bin/bash
    set -euo pipefail
    echo "Installing VS Code Insiders from Homebrew..."
    brew install --cask joshyorko/tools/vscode-insiders-linux
    echo "✓ VS Code Insiders installation complete"

[group('Dudley')]
dudley-vscode-extensions:
    #!/usr/bin/bash
    set -euo pipefail
    EXTENSIONS_FILE="/usr/share/ublue-os/vscode-extensions.list"

    if ! command -v code-insiders &>/dev/null; then
        echo "ERROR: VS Code Insiders not found. It should be pre-installed in the image."
        exit 1
    fi

    if [ ! -f "$EXTENSIONS_FILE" ]; then
        echo "ERROR: Extensions list not found at $EXTENSIONS_FILE"
        exit 1
    fi

    echo "Installing VS Code Insiders extensions..."
    declare -i installed=0
    declare -i failed=0
    while IFS= read -r ext || [ -n "$ext" ]; do
        [[ -z "$ext" || "$ext" =~ ^[[:space:]]*# ]] && continue
        ext=$(echo "$ext" | xargs)
        echo "  Installing: $ext"
        if code-insiders --install-extension "$ext" --force &>/dev/null; then
            ((installed++))
        else
            echo "    ⚠ Failed to install $ext"
            ((failed++))
        fi
    done < "$EXTENSIONS_FILE"

    echo ""
    echo "✓ Extensions installed: $installed"
    [ "$failed" -gt 0 ] && echo "⚠ Extensions failed: $failed"
    echo "Done!"

[group('Dudley')]
dudley-vscode-all:
    #!/usr/bin/bash
    set -euo pipefail
    ujust dudley-vscode-insiders
    ujust dudley-vscode-extensions
