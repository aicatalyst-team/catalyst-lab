#!/usr/bin/env bash
set -euo pipefail

# Install F*, Pulse, Z3, and proof-copilot for Project Tether

echo "=== Project Tether — Toolchain Installer ==="
echo ""

# --- Z3 ---
echo "--- Z3 ---"
if command -v z3 &>/dev/null; then
  echo "Z3 already installed: $(z3 --version)"
else
  echo "Installing Z3 via Homebrew..."
  brew install z3
fi

# --- F* + Pulse ---
echo ""
echo "--- F* + Pulse ---"
if command -v fstar.exe &>/dev/null; then
  echo "F* already installed: $(fstar.exe --version | head -1)"
else
  echo "Installing F* via official installer..."
  curl -fsSL https://aka.ms/install-fstar | bash -s -- --release
fi

# Verify Pulse is bundled
FSTAR_LIB=$(fstar.exe --locate_lib 2>/dev/null || echo "")
if [ -d "${FSTAR_LIB}/pulse" ]; then
  echo "Pulse: FOUND at ${FSTAR_LIB}/pulse"
else
  echo "Warning: Pulse libraries not found. Substrate specs will fail."
fi

# --- proof-copilot plugin for Claude Code ---
echo ""
echo "--- proof-copilot ---"
if command -v claude &>/dev/null; then
  echo "Installing proof-copilot plugin for Claude Code..."
  claude plugin marketplace add FStarLang/proof-copilot 2>/dev/null || true
  claude plugin install proof-copilot@proof-copilot 2>/dev/null || true
  echo "proof-copilot installed. Restart Claude Code to activate skills."
else
  echo "Claude Code CLI not found. Install proof-copilot manually:"
  echo "  claude plugin marketplace add FStarLang/proof-copilot"
  echo "  claude plugin install proof-copilot@proof-copilot"
fi

# --- Verify ---
echo ""
echo "=== Toolchain Status ==="
echo -n "Z3:              "; z3 --version 2>/dev/null || echo "NOT FOUND"
echo -n "F*:              "; fstar.exe --version 2>/dev/null | head -1 || echo "NOT FOUND"
echo -n "Pulse:           "; [ -d "${FSTAR_LIB}/pulse" ] && echo "OK" || echo "NOT FOUND"
echo -n "proof-copilot:   "; claude plugin list 2>/dev/null | grep -q proof-copilot && echo "OK" || echo "NOT FOUND"
echo ""
echo "Ensure ~/.local/bin is on your PATH:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
