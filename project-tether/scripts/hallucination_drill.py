#!/usr/bin/env python3
"""Hallucination Loop Prevention — Deep Drill-Down Demo

Dissects the hallucination persistence loop prevention mechanism
gate by gate, function by function, with F* proof evidence alongside
each Python call.

This is NOT a pass/fail demo. It exposes the internal mechanics so
you can explain exactly why each gate fires, what the F* compiler
proved about it, and how the attack would compound without it.

Usage:
    uv run python scripts/hallucination_drill.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "tests"))

from tether.gateway_client import (  # noqa: E402
    DomainSpec,
    InferenceChain,
    InferenceStep,
    MemoryEntry,
    MemoryIntent,
    MemoryState,
    Observation,
    PoisonPatterns,
    TetherGatewayClient,
    TrustLevel,
    _chain_well_formed,
    _identity_valid,
    _no_contradiction,
    _rule_obligation_met,
    extract_observations_from_messages,
    identity_rule,
    is_trusted,
)
from tether.owasp_asi06_vectors import DEFAULT_POISON_PATTERNS  # noqa: E402

# --- Terminal colors (matches scripts/demo.py) ---

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
WHITE = "\033[97m"

OK = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"


def banner():
    print(f"""
{BOLD}{CYAN}{"=" * 70}

  Hallucination Loop Prevention — Deep Drill-Down

  Project Tether: F*/Pulse separation logic + Z3 SMT solver
  Dissecting the proof mechanics gate by gate

{"=" * 70}{RESET}
""")


def phase_header(num: int, title: str, desc: str):
    print(f"\n{BOLD}{BLUE}{'━' * 70}")
    print(f"  Phase {num}: {title}")
    print(f"{'━' * 70}{RESET}")
    print(f"  {DIM}{desc}{RESET}\n")


def fstar_block(code: str):
    for line in code.strip().split("\n"):
        print(f"  {DIM}│ {line}{RESET}")
    print()


def result_line(label: str, passed: bool, detail: str = ""):
    icon = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
    extra = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {icon} {label}{extra}")


def value_line(label: str, value, color: str = WHITE):
    print(f"  {CYAN}{label}:{RESET} {color}{value}{RESET}")


# =====================================================================
# Phase 1: The Attack
# =====================================================================


def phase_1():
    phase_header(
        1,
        "The Attack",
        (
            "An AI agent observes a fact and fabricates an unrelated\n"
            "  conclusion. Without verification, this hallucination enters\n"
            "  memory and compounds on every subsequent turn."
        ),
    )

    print(f"  {BOLD}The scenario:{RESET}")
    print()
    value_line("Observation", '"The sky is blue"')
    value_line("Agent concludes", '"The economy will crash"', RED)
    value_line("Claimed rule", "Identity (conclusion must equal premise)")
    print()

    print(f"  {BOLD}The inference chain submitted to Tether:{RESET}")
    print(f"""
  {DIM}InferenceChain {{
    steps: [
      InferenceStep {{
        premises:   ["The sky is blue"]
        rule:       Identity
        conclusion: "The economy will crash"
      }}
    ]
    final_conclusion: "The economy will crash"
  }}{RESET}
""")

    print(f"  {BOLD}{RED}Why this is catastrophic without verification:{RESET}")
    print(f"""
  {YELLOW}Turn 1:{RESET} Agent observes "The sky is blue"
           Hallucinates "The economy will crash"
           {RED}Stores it in memory as established fact{RESET}

  {YELLOW}Turn 2:{RESET} Agent reads memory: "The economy will crash"
           Treats it as ground truth (it's in memory!)
           Derives: "We should sell all stocks immediately"
           {RED}Stores this too — now two false facts{RESET}

  {YELLOW}Turn 3:{RESET} Agent reads: "economy crashing" + "sell stocks"
           Concludes: "Financial crisis is imminent"
           {RED}The hallucination is now a self-reinforcing belief{RESET}

  {DIM}Each turn, the hallucination compounds. The agent's memory
  becomes an echo chamber of fabricated conclusions, each one
  "justified" by the previous fabrication. This is the
  hallucination persistence loop.{RESET}
""")


# =====================================================================
# Phase 2: Gate-by-Gate Dissection
# =====================================================================


def phase_2():
    phase_header(
        2,
        "Gate-by-Gate Dissection",
        (
            "We now call each internal verification function individually,\n"
            "  showing exactly what it checks and why it rejects.\n"
            "  Each Python function mirrors an F* function with a machine-\n"
            "  checked ensures clause."
        ),
    )

    obs_content = "The sky is blue"
    conclusion = "The economy will crash"
    step = InferenceStep(
        premises=[obs_content],
        rule=identity_rule(),
        conclusion=conclusion,
    )
    chain = InferenceChain(steps=[step], final_conclusion=conclusion)
    obs_contents = [obs_content]

    # --- Gate 2a: Premise grounding ---

    print(f"  {BOLD}Gate 2a: Premise Grounding (step_premises_valid){RESET}")
    print()
    value_line("known set", obs_contents)
    value_line("step.premises", step.premises)

    premises_ok = all(p in obs_contents for p in step.premises)
    result_line(
        f"Every premise in known? {premises_ok}",
        premises_ok,
        "The premise IS in the observation set — grounding passes",
    )
    print()

    print(f"  {DIM}F* function (TetherPredicates.fst:19-23):{RESET}")
    fstar_block("""
let step_premises_valid (known: list string) (step: inference_step) : bool =
  List.Tot.for_all
    (fun premise -> List.Tot.existsb (fun k -> k = premise) known)
    step.premises
""")

    print(f"  {YELLOW}Key insight:{RESET} Grounding alone is not enough. The premise")
    print("  IS a real observation. The problem is what the agent DOES with it.")
    print()

    # --- Gate 2b: Identity validation ---

    print(f"  {BOLD}Gate 2b: Identity Rule Validation (_identity_valid){RESET}")
    print()
    value_line("step.premises[0]", f'"{obs_content}"')
    value_line("step.conclusion", f'"{conclusion}"', RED)
    value_line("Are they equal?", f"{obs_content == conclusion}", RED)
    print()

    id_ok = _identity_valid(step)
    result_line(f"identity_valid → {id_ok}", id_ok, "Conclusion ≠ premise — identity rule VIOLATED")
    print()

    print(f"  {DIM}F* function (TetherPredicates.fst:54-57):{RESET}")
    fstar_block("""
let identity_valid (step: inference_step) : bool =
  match step.premises with
  | [single] -> step.step_conclusion = single    (* must be identical *)
  | _ -> false                                    (* must have exactly 1 premise *)
""")

    print(f"  {YELLOW}This is THE gate.{RESET} The identity rule requires character-for-")
    print("  character equality between premise and conclusion.")
    print("  'The sky is blue' != 'The economy will crash'.")
    print("  No amount of prompt engineering can make two different strings equal.")
    print()

    # --- Gate 2c: Rule obligation dispatch ---

    print(f"  {BOLD}Gate 2c: Rule Obligation Dispatch (_rule_obligation_met){RESET}")
    print()
    value_line("step.rule.kind", "IDENTITY")
    print(f"  {DIM}Dispatcher routes to identity_valid → already failed{RESET}")
    print()

    rule_ok = _rule_obligation_met(step)
    result_line(f"rule_obligation_met → {rule_ok}", rule_ok, "Semantic obligation not met")
    print()

    print(f"  {DIM}F* function (TetherPredicates.fst:79-85):{RESET}")
    fstar_block("""
let rule_obligation_met (step: inference_step) : bool =
  match step.rule with
  | RuleIdentity         -> identity_valid step
  | RuleExtraction ev    -> extraction_valid step ev
  | RuleAggregation ev   -> aggregation_valid step ev
  | RuleToolResult ev    -> tool_result_valid step ev
  | RuleDerivation ev    -> derivation_valid step ev
""")

    # --- Gate 2d: Chain well-formedness ---

    print(f"  {BOLD}Gate 2d: Chain Well-Formedness (_chain_well_formed){RESET}")
    print()

    chain_ok = _chain_well_formed(obs_contents, chain)
    result_line(
        f"chain_well_formed → {chain_ok}", chain_ok, "Chain is NOT well-formed — write blocked"
    )
    print()

    print(f"  {DIM}The recursive walk stopped at step 1:")
    print(f"    known = {obs_contents}")
    print(f"    step 1: premises grounded ✓, rule obligation ✗ → HALT{RESET}")
    print()

    print(f"  {DIM}F* function (TetherPredicates.fst:89-98):{RESET}")
    fstar_block("""
let rec chain_well_formed_aux (known: list string) (steps: list inference_step)
  : Tot bool (decreases steps)    (* <-- F* proves this terminates *)
= match steps with
  | [] -> true
  | s :: rest ->
    step_premises_valid known s &&
    rule_obligation_met s &&       (* <-- FAILS HERE for fabrication *)
    chain_well_formed_aux (s.step_conclusion :: known) rest
""")

    # --- The ensures clause ---

    print(f"  {BOLD}What the F* compiler proved about this:{RESET}")
    print()

    print(f"  {DIM}AgentReasoning.fst:9-17 — inference_sound:{RESET}")
    fstar_block("""
let inference_sound (observations: list observation)
                    (chain: inference_chain)
                    (conclusion: memory_entry)
  : Pure bool
    (requires True)
    (ensures fun b -> b ==>
      chain_well_formed (map obs_content observations) chain /\\
      chain.final_conclusion = conclusion.me_content)
""")

    print(f"  {YELLOW}Reading the ensures clause:{RESET}")
    print("  'If this function returns true (b ==> ...), then the chain")
    print("   is well-formed AND the conclusion matches.'")
    print("  Contrapositive: if the chain is NOT well-formed, this")
    print("  function CANNOT return true. Z3 verified this at compile time.")
    print()

    # --- The incorrectness lemma ---

    print(f"  {BOLD}F* Incorrectness Lemma (the converse proof):{RESET}")
    print()
    print(f"  {DIM}TetherLemmas.fst:45-53 — L1: identity_fabrication_rejected:{RESET}")
    fstar_block("""
let identity_fabrication_rejected (step: inference_step)
  : Lemma
    (requires
      RuleIdentity? step.rule /\\                  (* claims identity rule *)
      (match step.premises with
       | [p] -> p <> step.step_conclusion          (* but conclusion ≠ premise *)
       | _ -> True))
    (ensures rule_obligation_met step = false)     (* THEN rejection guaranteed *)
= ()   (* <-- trivial body: Z3 proves this automatically *)
""")

    print(f"  {YELLOW}This lemma says:{RESET} For ALL inference steps where the agent claims")
    print("  Identity but the conclusion differs from the premise, rejection")
    print("  is GUARANTEED. Not for one test case — for every possible input.")
    print("  The body is () because Z3 finds no counterexample.")
    print()

    # --- The norm test ---

    print(f"  {BOLD}F* Compile-Time Evaluation (same concrete input):{RESET}")
    print()
    print(f"  {DIM}TetherNormTests.fst:209-216:{RESET}")
    fstar_block("""
let _ = assert_norm (
  chain_well_formed
    ["The sky is blue"]
    ({ steps = [{ premises = ["The sky is blue"];
                  rule = RuleIdentity;
                  step_conclusion = "The economy will crash" }];
       final_conclusion = "The economy will crash" })
  = false)
""")

    print(f"  {YELLOW}assert_norm{RESET} forces F* to evaluate this expression inside the")
    print("  type checker — no Z3 needed. It confirms the spec returns false")
    print("  on THIS EXACT input. If it didn't, typechecking would fail.")
    print()


# =====================================================================
# Phase 3: Contrast with a Valid Write
# =====================================================================


def phase_3():
    phase_header(
        3,
        "Contrast — A Valid Write",
        (
            "Same gates, same functions, but with a legitimate observation.\n"
            "  Shows what success looks like and why the gates ALLOW it."
        ),
    )

    content = "GPU utilization at 87%"
    step = InferenceStep(premises=[content], rule=identity_rule(), conclusion=content)
    chain = InferenceChain(steps=[step], final_conclusion=content)
    obs_contents = [content]

    print(f"  {BOLD}Scenario:{RESET} Agent observes GPU metrics, stores them as-is.")
    print()
    value_line("Observation", f'"{content}"')
    value_line("Conclusion", f'"{content}"', GREEN)
    value_line("Rule", "Identity (conclusion = premise)")
    print()

    # Walk the gates
    premises_ok = all(p in obs_contents for p in step.premises)
    result_line("Premise grounding", premises_ok, f"'{content}' is in known set")

    id_ok = _identity_valid(step)
    result_line("identity_valid", id_ok, "conclusion = premise (identical strings)")

    rule_ok = _rule_obligation_met(step)
    result_line("rule_obligation_met", rule_ok, "Identity dispatches → identity_valid → True")

    chain_ok = _chain_well_formed(obs_contents, chain)
    result_line("chain_well_formed", chain_ok, "Chain is well-formed")
    print()

    print(f"  {DIM}known set evolution:{RESET}")
    print(f"    Start:    {obs_contents}")
    print(f"    After s1: {obs_contents + [content]}  (conclusion added)")
    print("    Final:    last step conclusion = final_conclusion ✓")
    print()

    # Run full pipeline
    gw = TetherGatewayClient()
    entry = MemoryEntry(key="observation_summary", content=content, source_trusted=True)
    intent = MemoryIntent(
        agent_id="demo",
        observations=[Observation(source="otel-collector", content=content)],
        chain=chain,
        conclusion=entry,
        existing=MemoryState(),
        bound=2200,
        poison_patterns=PoisonPatterns(**DEFAULT_POISON_PATTERNS),
        domain_spec=DomainSpec(required_keys=["observation_summary"]),
    )
    resp = gw.verify_write(intent)

    print(f"  {BOLD}Full pipeline result:{RESET}")
    for prop in resp.properties_satisfied:
        result_line(prop, True)
    print()
    if resp.certificate:
        print(f"  {GREEN}Certificate issued:{RESET}")
        print(f"    content_hash: {resp.certificate.content_hash[:32]}...")
        print(f"    rule:         {resp.certificate.rule_used.kind.value}")
        print(f"    properties:   {len(resp.certificate.properties_satisfied)} verified")
    print()

    print(f"  {DIM}F* norm test confirming this input passes")
    print(f"  (TetherNormTests.fst:171-178):{RESET}")
    fstar_block("""
let _ = assert_norm (
  chain_well_formed
    ["GPU utilization at 87%"]
    ({ steps = [{ premises = ["GPU utilization at 87%"];
                  rule = RuleIdentity;
                  step_conclusion = "GPU utilization at 87%" }];
       final_conclusion = "GPU utilization at 87%" })
  = true)
""")


# =====================================================================
# Phase 4: Multi-Step Chain Attack
# =====================================================================


def phase_4():
    phase_header(
        4,
        "Multi-Step Chain Attack",
        (
            "A more sophisticated attempt: valid step 1 to build trust,\n"
            "  then fabricated step 2. Shows that chain_well_formed_aux\n"
            "  catches fabrication even after valid earlier steps."
        ),
    )

    obs = "The sky is blue"
    fabricated = "The economy will crash"

    step1 = InferenceStep(premises=[obs], rule=identity_rule(), conclusion=obs)
    step2 = InferenceStep(premises=[obs], rule=identity_rule(), conclusion=fabricated)
    chain = InferenceChain(steps=[step1, step2], final_conclusion=fabricated)

    print(f"  {BOLD}The attack:{RESET}")
    print(f"    Step 1: premise='{obs}' → conclusion='{obs}' (valid identity)")
    print(f"    Step 2: premise='{obs}' → conclusion='{fabricated}' {RED}(fabricated){RESET}")
    print()

    print(f"  {BOLD}Walking chain_well_formed_aux:{RESET}")
    print()

    known = {obs}
    print(f"  {DIM}Initial known set: {list(known)}{RESET}")
    print()

    # Step 1
    s1_premises_ok = all(p in known for p in step1.premises)
    s1_rule_ok = _rule_obligation_met(step1)
    result_line("Step 1 — premises grounded", s1_premises_ok)
    result_line("Step 1 — rule_obligation_met (identity: conclusion = premise)", s1_rule_ok)
    known.add(step1.conclusion)
    print(f"         {DIM}known grows to: {list(known)}{RESET}")
    print()

    # Step 2
    s2_premises_ok = all(p in known for p in step2.premises)
    s2_rule_ok = _rule_obligation_met(step2)
    s2_id_ok = _identity_valid(step2)
    result_line(
        "Step 2 — premises grounded", s2_premises_ok, f"'{obs}' is in known (added at init)"
    )
    result_line("Step 2 — identity_valid", s2_id_ok, f"'{obs}' ≠ '{fabricated}'")
    result_line("Step 2 — rule_obligation_met", s2_rule_ok, "Identity obligation FAILED")
    print()

    chain_ok = _chain_well_formed([obs], chain)
    result_line(
        f"chain_well_formed → {chain_ok}", chain_ok, "Step 1 passing does NOT launder step 2"
    )
    print()

    print(f"  {YELLOW}Key insight:{RESET} chain_well_formed_aux checks EVERY step")
    print("  independently. A valid step 1 cannot 'vouch for' step 2.")
    print("  The known set accumulates conclusions, but each new step")
    print("  must still satisfy its own rule obligation.")
    print()

    print(f"  {DIM}F* enforces this structurally — the recursive call at")
    print("  TetherPredicates.fst:97 only continues if the current step passes:")
    print("    step_premises_valid known s && rule_obligation_met s &&")
    print(f"    chain_well_formed_aux (s.step_conclusion :: known) rest{RESET}")
    print()


# =====================================================================
# Phase 5: The Consistency Gate (P2)
# =====================================================================


def phase_5():
    phase_header(
        5,
        "The Consistency Gate (P2)",
        (
            "Second line of defense: even if a hallucination somehow\n"
            "  passed P1, the consistency check prevents the reinforcement\n"
            "  loop by blocking contradictory writes."
        ),
    )

    print(f"  {BOLD}Scenario:{RESET} Agent already stored a fact. Now it tries to")
    print("  overwrite it with contradictory content.")
    print()

    existing_entry = MemoryEntry(
        key="summary",
        content="The sky is blue",
        source_trusted=True,
    )
    existing = MemoryState(facts=[existing_entry])

    new_entry = MemoryEntry(
        key="summary",
        content="The economy will crash",
        source_trusted=True,
    )

    value_line("Existing fact", 'key="summary", content="The sky is blue"')
    value_line("New fact", 'key="summary", content="The economy will crash"', RED)
    print()

    # Call _no_contradiction directly
    consistent = _no_contradiction(new_entry, existing)
    result_line(
        f"no_contradiction → {consistent}",
        consistent,
        "Same key, different content → CONTRADICTION",
    )
    print()

    print(f"  {BOLD}How it detects the contradiction:{RESET}")
    print()
    print(f"    {DIM}for each fact in existing.facts:")
    print(f"      fact.key = '{existing_entry.key}' == new.key = '{new_entry.key}'  → same key")
    print(f"      fact.content = '{existing_entry.content}'")
    print(f"      new.content  = '{new_entry.content}'")
    print(f"      content differs → contradicts = True → no_contradiction = False{RESET}")
    print()

    print(f"  {DIM}F* predicate (TetherPredicates.fst:113-120):{RESET}")
    fstar_block("""
let contradicts (a b: memory_entry) : bool =
  a.me_key = b.me_key && not (a.me_content = b.me_content)

let no_contradiction (new_fact: memory_entry) (existing: memory_state) : bool =
  List.Tot.for_all (fun f -> not (contradicts new_fact f)) existing.facts
""")

    print(f"  {BOLD}F* Incorrectness Lemma — the converse proof:{RESET}")
    print()
    print(f"  {DIM}TetherLemmas.fst:149-173 — L7: contradiction_rejected:{RESET}")
    fstar_block("""
let contradiction_rejected
  (new_fact: memory_entry)
  (existing: memory_state)
  (witness: memory_entry)       (* <-- the contradicting entry *)
  : Lemma
    (requires
      List.Tot.memP witness existing.facts /\\   (* witness is in memory *)
      witness.me_key = new_fact.me_key /\\       (* same key *)
      ~(witness.me_content = new_fact.me_content)) (* different content *)
    (ensures no_contradiction new_fact existing = false) (* THEN rejected *)
""")

    print(f"  {YELLOW}This is the only lemma with a non-trivial proof body.{RESET}")
    print("  It uses a recursive auxiliary function to walk the fact list")
    print("  and locate the contradicting witness. Z3 alone doesn't find")
    print("  the proof — F* guides it with the recursive structure.")
    print()

    print(f"  {YELLOW}Why P2 prevents reinforcement:{RESET}")
    print("  Turn 1: agent stores 'The sky is blue' under key 'summary'")
    print("  Turn 2: agent tries to store 'The economy will crash' under 'summary'")
    print("  P2 catches it — same key, different content. The hallucination")
    print("  cannot overwrite established knowledge.")
    print()


# =====================================================================
# Phase 6: The Laundering Attack
# =====================================================================


def phase_6():
    phase_header(
        6,
        "The Laundering Attack",
        (
            "The agent tries to launder its own output as an observation\n"
            "  by injecting it into the message history. Three defenses\n"
            "  prevent this."
        ),
    )

    messages = [
        {"role": "user", "content": "What is the weather?"},
        {"role": "assistant", "content": "The economy will crash"},
        {"role": "tool", "content": "Temperature: 72F", "tool_call_id": "tc-1"},
    ]

    print(f"  {BOLD}Message history the agent submits:{RESET}")
    for msg in messages:
        role_color = GREEN if msg["role"] == "user" else (YELLOW if msg["role"] == "tool" else RED)
        print(f"    {role_color}{msg['role']:>10}{RESET}: {msg['content']}")
    print()

    print(f"  {BOLD}Defense 1: extract_observations_from_messages{RESET}")
    print()
    observations = extract_observations_from_messages(messages)
    print(f"  {DIM}Only 'user' and 'tool' messages become observations.{RESET}")
    print(f"  {DIM}'assistant' messages are the agent's own output — dropped.{RESET}")
    print()
    for obs in observations:
        result_line(f"{obs.source}: '{obs.content}'", True, f"trust={obs.trust.value}")
    print()
    has_assistant = any("economy" in obs.content.lower() for obs in observations)
    result_line(
        "Assistant content in observations?",
        not has_assistant,
        f"{'LEAKED — BUG' if has_assistant else 'Correctly excluded'}",
    )
    print()

    print(f"  {DIM}Python (gateway_client.py:363-382):{RESET}")
    fstar_block("""
def extract_observations_from_messages(messages):
    for msg in messages:
        role = msg.get("role", "")
        if role == "tool":           # ← only tool messages
            observations.append(...)
        elif role == "user":         # ← and user messages
            observations.append(...)
        # assistant messages: silently dropped
""")

    print(f"  {BOLD}Defense 2: Trust level classification{RESET}")
    print()
    print("  Even if an attacker manually injects an Observation with")
    print("  the fabricated content, they must assign a trust level:")
    print()
    for level in TrustLevel:
        trusted = is_trusted(level)
        icon = f"{GREEN}trusted{RESET}" if trusted else f"{RED}untrusted{RESET}"
        print(f"    {level.value:20s}  →  {icon}")
    print()

    print(f"  {DIM}F* function (TetherPredicates.fst:9-15):{RESET}")
    fstar_block("""
let is_trusted (t: trust_level) : bool =
  match t with
  | DirectObservation -> true
  | ToolOutput        -> true
  | ExternalInput     -> true
  | AgentGenerated    -> false    (* <-- agent's own output *)
  | Unverified        -> false
""")

    print(f"  {BOLD}Defense 3: P3 source_trusted check{RESET}")
    print()
    print("  The not_poisoned gate in AgentReasoning.fst requires")
    print("  entry.me_source_trusted = true. An agent-generated entry")
    print("  with source_trusted=false is rejected at P3:")
    print()
    print(f"  {DIM}AgentReasoning.fst:33-42:{RESET}")
    fstar_block("""
let not_poisoned (entry: memory_entry) (pp: poison_patterns)
  : Pure bool (requires True)
    (ensures fun b -> b ==>
      content_safe entry.me_content pp /\\
      entry.me_source_trusted)        (* <-- must be trusted *)
""")

    print(f"  {YELLOW}Three-layer defense against laundering:{RESET}")
    print("    1. Message extraction drops assistant messages")
    print("    2. Trust classification marks agent output as untrusted")
    print("    3. P3 gate rejects entries with source_trusted=false")
    print()


# =====================================================================
# Phase 7: Evidence Cross-Reference Table
# =====================================================================


def phase_7():
    phase_header(
        7,
        "Evidence Cross-Reference",
        (
            "Four independent layers of evidence that the hallucination\n"
            "  'The sky is blue' → 'The economy will crash' is rejected.\n"
            "  Each layer uses a different verification technique."
        ),
    )

    print(f"  {BOLD}Layer 1: Universal Proof (∀ inputs){RESET}")
    print(f"  {DIM}Source: AgentReasoning.fst:15-17, ensures clause{RESET}")
    print("  Method: Z3 SMT solver checks at F* compile time")
    print("  Scope:  For ALL observations, chains, and conclusions —")
    print("          if inference_sound returns true, the chain is well-formed")
    print("          and the conclusion matches. No counterexample exists.")
    print()

    print(f"  {BOLD}Layer 2: Incorrectness Lemma (∀ fabricated inputs){RESET}")
    print(f"  {DIM}Source: TetherLemmas.fst:45-53, identity_fabrication_rejected{RESET}")
    print("  Method: Z3 proves the converse — rejection is guaranteed")
    print("  Scope:  For ALL steps claiming Identity where conclusion ≠ premise,")
    print("          rule_obligation_met returns false. The gate is tight —")
    print("          it doesn't just accept valid inputs, it rejects invalid ones.")
    print()

    print(f"  {BOLD}Layer 3: Compile-Time Evaluation (this specific input){RESET}")
    print(f"  {DIM}Source: TetherNormTests.fst:209-216, assert_norm{RESET}")
    print("  Method: F* normalizer evaluates the function at type-check time")
    print("  Scope:  The EXACT input ('The sky is blue' → 'The economy will crash')")
    print("          evaluates to false inside the F* type checker. No SMT needed —")
    print("          pure computation. If the spec were wrong, typechecking fails.")
    print()

    print(f"  {BOLD}Layer 4: Runtime Test (this specific input at runtime){RESET}")
    print(f"  {DIM}Source: test_p1_semantic.py:302-310{RESET}")
    print("         test_sky_blue_economy_crash_rejected")
    print("  Method: pytest exercises the Python mirror of the F* logic")
    print("  Scope:  The same input runs through the Python gateway_client and")
    print("          returns CONTENT_FAILED. Confirms spec and implementation agree.")
    print()

    print(f"  {BOLD}{'─' * 70}{RESET}")
    print(f"  {BOLD}{'Layer':<25} {'Quantifier':<15} {'Technique':<15} {'Checked By':<15}{RESET}")
    print(f"  {'─' * 70}")
    print(f"  {'Universal proof':<25} {'∀ inputs':<15} {'SMT solving':<15} {'Z3':<15}")
    print(f"  {'Incorrectness lemma':<25} {'∀ fabricated':<15} {'SMT solving':<15} {'Z3':<15}")
    checker = "F* typechecker"
    print(f"  {'Compile-time eval':<25} {'∃ (this one)':<15} {'Normalization':<15} {checker:<15}")
    print(f"  {'Runtime test':<25} {'∃ (this one)':<15} {'Execution':<15} {'pytest':<15}")
    print(f"  {'─' * 70}")
    print()
    print(f"  {YELLOW}Reading this table:{RESET}")
    print("  Rows 1-2 are UNIVERSAL — they cover every possible input.")
    print("  Rows 3-4 are EXISTENTIAL — they confirm one specific case.")
    print("  Together: the property holds for all inputs (rows 1-2),")
    print("  AND we've verified the spec computes correctly on concrete")
    print("  inputs matching our test suite (rows 3-4).")
    print()


# =====================================================================
# Phase 8: Full Pipeline Comparison
# =====================================================================


def phase_8():
    phase_header(
        8,
        "Full Pipeline — Side by Side",
        (
            "Run verify_write end-to-end for both cases, showing where\n"
            "  properties accumulate (valid) and where they stop (hallucination)."
        ),
    )

    pp = PoisonPatterns(**DEFAULT_POISON_PATTERNS)

    # --- Valid write ---

    print(f"  {BOLD}{GREEN}Case A: Valid write{RESET}")
    print("  observation = conclusion = 'GPU utilization at 87%'")
    print()

    valid_content = "GPU utilization at 87%"
    gw_valid = TetherGatewayClient()
    valid_intent = MemoryIntent(
        agent_id="demo",
        observations=[Observation(source="otel", content=valid_content)],
        chain=InferenceChain(
            steps=[
                InferenceStep(
                    premises=[valid_content], rule=identity_rule(), conclusion=valid_content
                )
            ],
            final_conclusion=valid_content,
        ),
        conclusion=MemoryEntry(key="obs", content=valid_content, source_trusted=True),
        existing=MemoryState(),
        bound=2200,
        poison_patterns=pp,
        domain_spec=DomainSpec(required_keys=["obs"]),
    )
    valid_resp = gw_valid.verify_write(valid_intent)

    for prop in valid_resp.properties_satisfied:
        result_line(prop, True)
    print(f"  → {GREEN}{BOLD}{valid_resp.result.value}{RESET}")
    print()

    # --- Hallucination ---

    print(f"  {BOLD}{RED}Case B: Hallucination{RESET}")
    print("  observation = 'The sky is blue', conclusion = 'The economy will crash'")
    print()

    gw_hallu = TetherGatewayClient()
    hallu_intent = MemoryIntent(
        agent_id="demo",
        observations=[Observation(source="agent", content="The sky is blue")],
        chain=InferenceChain(
            steps=[
                InferenceStep(
                    premises=["The sky is blue"],
                    rule=identity_rule(),
                    conclusion="The economy will crash",
                )
            ],
            final_conclusion="The economy will crash",
        ),
        conclusion=MemoryEntry(key="obs", content="The economy will crash", source_trusted=True),
        existing=MemoryState(),
        bound=2200,
        poison_patterns=pp,
        domain_spec=DomainSpec(required_keys=["obs"]),
    )
    hallu_resp = gw_hallu.verify_write(hallu_intent)

    if hallu_resp.properties_satisfied:
        for prop in hallu_resp.properties_satisfied:
            result_line(prop, True)
    result_line("P1:inference_sound", False, "chain_well_formed → False, HALT")
    print(f"  → {RED}{BOLD}{hallu_resp.result.value}{RESET}")
    print()

    # --- The Pulse contract ---

    print(f"  {BOLD}The Pulse ensures clause — the complete contract:{RESET}")
    print()
    print(f"  {DIM}VerifiedWrite.fst:32-44:{RESET}")
    fstar_block("""
fn verified_write (agent ...) (region: memory_region) (...)
  (#v: erased string)
  requires region |-> v                (* region holds old value *)
  returns r: write_result
  ensures (match r with
    | WriteOk ->
        region |-> conclusion.me_content **  (* NEW value written *)
        pure (
          chain_well_formed (...) chain /\\    (* P1: reasoning sound *)
          chain.final_conclusion = conclusion.me_content /\\
          no_contradiction conclusion existing /\\  (* P2: consistent *)
          content_safe conclusion.me_content pp /\\ (* P3: not poisoned *)
          conclusion.me_source_trusted /\\
          memory_is_complete (...) /\\              (* P4: complete *)
          String.length conclusion.me_content <= bound)  (* P5: bounded *)
    | ContentFailed      -> region |-> v   (* UNCHANGED on failure *)
    | PoisonDetected     -> region |-> v
    | IncompleteCoverage -> region |-> v
    | BoundsFailed       -> region |-> v)
""")

    print(f"  {YELLOW}Reading the contract:{RESET}")
    print("    region |-> v          = 'region currently holds value v'")
    print("    region |-> content    = 'region now holds the new content'")
    print("    **                    = separating conjunction (independent ownership)")
    print("    pure (...)            = these logical properties hold")
    print("    | ContentFailed → v   = on ANY failure, region is UNCHANGED")
    print()
    print(f"  {YELLOW}The F* compiler (with Z3) verified:{RESET}")
    print("    1. WriteOk is ONLY returned when all properties hold")
    print("    2. On failure, memory is NEVER corrupted (region |-> v)")
    print("    3. This is true for ALL possible inputs, not just test cases")
    print()


# =====================================================================
# Main
# =====================================================================


def main():
    banner()
    phase_1()
    phase_2()
    phase_3()
    phase_4()
    phase_5()
    phase_6()
    phase_7()
    phase_8()

    print(f"{BOLD}{CYAN}{'=' * 70}")
    print("  End of Drill-Down")
    print(f"{'=' * 70}{RESET}")
    print()
    print(f"  {DIM}This demo called the same functions the production pipeline calls.")
    print("  Each Python function mirrors an F* function with a machine-checked")
    print("  ensures clause. The F* lemmas prove rejection is guaranteed for all")
    print(f"  fabricated inputs — not just the ones we tested.{RESET}")
    print()


if __name__ == "__main__":
    main()
