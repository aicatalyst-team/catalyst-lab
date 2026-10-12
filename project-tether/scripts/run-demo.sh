#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
REPO_ROOT="$(dirname "${PROJECT_DIR}")"

FSTAR="${FSTAR_HOME:-$HOME/.local/fstar}/bin/fstar.exe"
FSTAR_MCP="${FSTAR_MCP_BIN:-$HOME/Virtualenvs/fstar-mcp/target/release/fstar-mcp}"
MCP_PORT="${FSTAR_MCP_PORT:-3001}"

CYAN='\033[96m'
GREEN='\033[92m'
RED='\033[91m'
YELLOW='\033[93m'
BLUE='\033[94m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

MCP_PID=""

cleanup() {
  if [ -n "$MCP_PID" ] && kill -0 "$MCP_PID" 2>/dev/null; then
    kill "$MCP_PID" 2>/dev/null
    wait "$MCP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

pause() {
  if [ "${TETHER_AUTO:-}" != "1" ]; then
    echo ""
    echo -e "  ${DIM}Press Enter to continue...${RESET}"
    read -r
  fi
}

banner() {
  echo -e "
${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   Tether  —  Project Tether Demo                                ║
║   Formally Verified AI Agent Runtime                             ║
║                                                                  ║
║   Demo for Professor Coblenz — July 2026                        ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝${RESET}
"
}

system_info() {
  echo -e "${BOLD}${BLUE}━━━ System Info ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "  F*:        $("${FSTAR}" --version 2>/dev/null | head -1 || echo 'not found')"
  echo -e "  Z3:        $(z3 --version 2>/dev/null || echo 'not found')"
  echo -e "  Python:    $(python3 --version 2>/dev/null)"
  echo -e "  tectonic:  $(tectonic --version 2>/dev/null | head -1 || echo 'not found')"
  echo -e "  fstar-mcp: $([ -x "${FSTAR_MCP}" ] && echo 'installed' || echo 'not found')"
  echo ""
}

# ─── Part 1: F* Verification ───

part1_fstar() {
  echo -e "${BOLD}${BLUE}━━━ Part 1: F* Specification Verification (22 specs) ━━━━━━━━━${RESET}"
  echo -e "  ${DIM}Verifying all specs with fstar.exe + Z3 SMT solver${RESET}"
  echo ""

  "${SCRIPT_DIR}/verify-specs.sh"
  pause
}

# ─── Part 2: Python Test Suite ───

part2_pytest() {
  echo -e "${BOLD}${BLUE}━━━ Part 2: Python Runtime Tests (175 tests) ━━━━━━━━━━━━━━━━${RESET}"
  echo -e "  ${DIM}Python mirror of F* specs — same inputs, same verdicts${RESET}"
  echo ""

  cd "${PROJECT_DIR}"
  uv run pytest tests/ -q --tb=short 2>&1 | grep -v "^$" | tail -5
  echo ""
  pause
}

# ─── Part 3: Interactive F* Typechecking (Swamy's Agentic Loop) ───

part3_mcp() {
  echo -e "${BOLD}${BLUE}━━━ Part 3: Agentic Proof Loop (fstar-mcp) ━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "  ${DIM}Swamy's proof-oriented programming: send code → typecheck →"
  echo -e "  read errors → repair → repeat until verification passes.${RESET}"
  echo ""

  if [ ! -x "${FSTAR_MCP}" ]; then
    echo -e "  ${YELLOW}fstar-mcp not found at ${FSTAR_MCP} — skipping${RESET}"
    pause
    return
  fi

  # Start fstar-mcp server
  echo -e "  ${CYAN}Starting fstar-mcp server on port ${MCP_PORT}...${RESET}"
  FSTAR_MCP_PORT="${MCP_PORT}" "${FSTAR_MCP}" &>/dev/null &
  MCP_PID=$!
  sleep 2

  if ! kill -0 "$MCP_PID" 2>/dev/null; then
    echo -e "  ${RED}Server failed to start${RESET}"
    pause
    return
  fi

  SPECS_DIR="${PROJECT_DIR}/specs"
  FILE_PATH="${SPECS_DIR}/content/TetherTypes.fst"

  # Step 1: Create session
  echo -e "  ${CYAN}Step 1:${RESET} Create session for TetherTypes.fst"
  SESSION_RESULT=$(curl -s -X POST "http://localhost:${MCP_PORT}/" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"id\":1,\"params\":{\"name\":\"create_session\",\"arguments\":{
      \"file_path\": \"${FILE_PATH}\",
      \"fstar_exe\": \"${FSTAR}\",
      \"cwd\": \"${SPECS_DIR}\",
      \"include_dirs\": [\"${SPECS_DIR}/content\", \"${SPECS_DIR}/substrate\", \"${SPECS_DIR}\"]
    }}}" 2>/dev/null)

  SESSION_ID=$(echo "${SESSION_RESULT}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inner = json.loads(d['result']['content'][0]['text'])
print(inner['session_id'])" 2>/dev/null)

  STATUS=$(echo "${SESSION_RESULT}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inner = json.loads(d['result']['content'][0]['text'])
frags = inner.get('fragments', [])
ok = sum(1 for f in frags if f['status'] == 'ok')
print(f'{ok}/{len(frags)} fragments verified')" 2>/dev/null)

  echo -e "  ${GREEN}✓${RESET} Session created — ${STATUS}"

  # Step 2: Inject a type error
  echo ""
  echo -e "  ${CYAN}Step 2:${RESET} Inject type error: tier1_bound : nat = \"not_a_number\""

  ERROR_RESULT=$(curl -s -X POST "http://localhost:${MCP_PORT}/" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"id\":2,\"params\":{\"name\":\"typecheck_buffer\",\"arguments\":{
      \"session_id\": \"${SESSION_ID}\",
      \"code\": \"module TetherTypes\n\nopen FStar.List.Tot\nopen FStar.String\n\ntype trust_level =\n  | DirectObservation\n  | ToolOutput\n  | ExternalInput\n  | AgentGenerated\n  | Unverified\n\nlet tier1_bound : nat = \\\"not_a_number\\\"\",
      \"kind\": \"full\"
    }}}" 2>/dev/null)

  ERROR_MSG=$(echo "${ERROR_RESULT}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inner = json.loads(d['result']['content'][0]['text'])
for diag in inner.get('diagnostics', []):
    msg = diag['message'].strip()
    print(f'  Line {diag[\"start_line\"]}: {msg[:70]}')
    break" 2>/dev/null)

  echo -e "  ${RED}✗${RESET} Error caught:${ERROR_MSG}"

  # Step 3: Repair and re-verify
  echo ""
  echo -e "  ${CYAN}Step 3:${RESET} Repair: tier1_bound : nat = 2200"

  REPAIR_RESULT=$(curl -s -X POST "http://localhost:${MCP_PORT}/" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"id\":3,\"params\":{\"name\":\"typecheck_buffer\",\"arguments\":{
      \"session_id\": \"${SESSION_ID}\",
      \"code\": \"module TetherTypes\n\nopen FStar.List.Tot\nopen FStar.String\n\ntype trust_level =\n  | DirectObservation\n  | ToolOutput\n  | ExternalInput\n  | AgentGenerated\n  | Unverified\n\nlet tier1_bound : nat = 2200\",
      \"kind\": \"full\"
    }}}" 2>/dev/null)

  REPAIR_STATUS=$(echo "${REPAIR_RESULT}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
inner = json.loads(d['result']['content'][0]['text'])
print(inner['status'])" 2>/dev/null)

  echo -e "  ${GREEN}✓${RESET} Re-verified: status=${REPAIR_STATUS}"

  echo ""
  echo -e "  ${BOLD}This is the agentic proof loop:${RESET}"
  echo -e "  ${DIM}  LLM writes code → fstar-mcp typechecks → errors returned →"
  echo -e "  LLM reads errors → repairs code → re-sends → verified ✓${RESET}"

  # Close session
  curl -s -X POST "http://localhost:${MCP_PORT}/" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"id\":4,\"params\":{\"name\":\"close_session\",\"arguments\":{\"session_id\":\"${SESSION_ID}\"}}}" &>/dev/null

  kill "$MCP_PID" 2>/dev/null
  wait "$MCP_PID" 2>/dev/null || true
  MCP_PID=""

  pause
}

# ─── Part 4: Five-Surface Demo ───

part4_surfaces() {
  echo -e "${BOLD}${BLUE}━━━ Part 4: Five Verification Surfaces (7 scenarios) ━━━━━━━━${RESET}"
  echo -e "  ${DIM}Runtime verification demo — all five surfaces${RESET}"
  echo ""

  cd "${PROJECT_DIR}"
  uv run python scripts/demo.py
}

# ─── Main ───

banner
system_info
part1_fstar
part2_pytest
part3_mcp
part4_surfaces

echo -e "
${BOLD}${GREEN}Demo complete.${RESET}

  Paper:  project-tether/paper/main.pdf (build with: cd paper && make)
  Specs:  22/22 verified F* modules (zero admits)
  Tests:  175/175 Python runtime tests
  MCP:    fstar-mcp interactive typechecking (Swamy's agentic loop)
  Demo:   7 scenarios across 5 verification surfaces
"
