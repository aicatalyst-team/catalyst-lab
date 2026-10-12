#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
SPECS_DIR="${PROJECT_DIR}/specs"

FSTAR="${FSTAR_HOME:-$HOME/.local/fstar}/bin/fstar.exe"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=== Project Tether — Spec Verification ==="
echo "Specs dir: ${SPECS_DIR}"
echo "F*:        ${FSTAR}"
echo ""

if ! command -v "${FSTAR}" &>/dev/null && [ ! -x "${FSTAR}" ]; then
  echo -e "${RED}Error: fstar.exe not found${NC}"
  echo "Install via: curl -fsSL https://aka.ms/install-fstar | bash -s -- --release"
  exit 1
fi

PASS=0
FAIL=0
TOTAL=0

verify_file() {
  local f="$1"
  local rel="${f#${PROJECT_DIR}/}"
  TOTAL=$((TOTAL + 1))

  printf "  %-55s " "${rel}"

  local output
  if output=$("${FSTAR}" \
    --include "${SPECS_DIR}/content" \
    --include "${SPECS_DIR}/substrate" \
    --include "${SPECS_DIR}" \
    "${f}" 2>&1); then
    echo -e "${GREEN}PASS${NC}"
    PASS=$((PASS + 1))
  else
    echo -e "${RED}FAIL${NC}"
    echo "${output}" | grep -E "Error|error" | head -10
    FAIL=$((FAIL + 1))
  fi
}

cd "${SPECS_DIR}"

echo "--- Shared types and predicates ---"
verify_file "${SPECS_DIR}/content/TetherTypes.fst"
verify_file "${SPECS_DIR}/content/TetherPredicates.fst"

echo ""
echo "--- P3: Poison detection ---"
verify_file "${SPECS_DIR}/content/PoisonDetection.fsti"
verify_file "${SPECS_DIR}/content/PoisonDetection.fst"

echo ""
echo "--- P4: Completeness checking ---"
verify_file "${SPECS_DIR}/content/CompletenessCheck.fsti"
verify_file "${SPECS_DIR}/content/CompletenessCheck.fst"

echo ""
echo "--- Content layer (P1–P4) ---"
verify_file "${SPECS_DIR}/content/AgentReasoning.fsti"
verify_file "${SPECS_DIR}/content/AgentReasoning.fst"

echo ""
echo "--- Substrate layer (P5, P7) ---"
verify_file "${SPECS_DIR}/substrate/AgentState.fsti"
verify_file "${SPECS_DIR}/substrate/AgentState.fst"

echo ""
echo "--- Tool scope (P9–P10) — scaffold ---"
verify_file "${SPECS_DIR}/substrate/ToolScope.fsti"
verify_file "${SPECS_DIR}/substrate/ToolScope.fst"

echo ""
echo "--- Surface 2: Skill verification (code generation) ---"
verify_file "${SPECS_DIR}/content/SkillVerification.fsti"
verify_file "${SPECS_DIR}/content/SkillVerification.fst"

echo ""
echo "--- Surface 4: Temporal validity ---"
verify_file "${SPECS_DIR}/content/TemporalValidity.fsti"
verify_file "${SPECS_DIR}/content/TemporalValidity.fst"

echo ""
echo "--- Surface 5: Multi-agent proof transport ---"
verify_file "${SPECS_DIR}/substrate/ProofTransport.fsti"
verify_file "${SPECS_DIR}/substrate/ProofTransport.fst"

echo ""
echo "--- Normalization tests (assert_norm on concrete inputs) ---"
verify_file "${SPECS_DIR}/content/TetherNormTests.fst"

echo ""
echo "--- Incorrectness lemmas (rejection is necessary) ---"
verify_file "${SPECS_DIR}/content/TetherLemmas.fst"

echo ""
echo "--- Composed verified write ---"
verify_file "${SPECS_DIR}/VerifiedWrite.fst"

echo ""
echo "--- Composed verified skill write (Surface 2 + P5+P7) ---"
verify_file "${SPECS_DIR}/VerifiedSkillWrite.fst"

echo ""
echo "=== Results ==="
echo -e "Total: ${TOTAL}  ${GREEN}Pass: ${PASS}${NC}  ${RED}Fail: ${FAIL}${NC}"

if [ "${FAIL}" -gt 0 ]; then
  exit 1
fi

echo ""
echo -e "${GREEN}Phase 3 deliverable: All five verification surfaces — P1-P10${NC}"
