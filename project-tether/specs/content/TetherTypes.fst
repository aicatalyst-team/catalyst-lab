module TetherTypes

open FStar.List.Tot
open FStar.String

(* --- Observation Provenance --- *)

type trust_level =
  | DirectObservation
  | ToolOutput
  | ExternalInput
  | AgentGenerated
  | Unverified

noeq
type observation = {
  obs_source: string;
  obs_content: string;
  obs_trust: trust_level;
  obs_tool_call_id: option string;
}

(* --- Inference Rule Evidence --- *)

noeq
type extraction_evidence = {
  ext_source_premise: string;
}

noeq
type aggregation_evidence = {
  agg_source_premises: list string;
}

noeq
type tool_evidence = {
  te_tool_name: string;
  te_call_id: string;
  te_tool_trusted: bool;
}

noeq
type derivation_evidence = {
  de_domain_rule_id: string;
}

(* --- Inference Rule Catalog --- *)

noeq
type inference_rule =
  | RuleIdentity
  | RuleExtraction  : ev:extraction_evidence  -> inference_rule
  | RuleAggregation : ev:aggregation_evidence -> inference_rule
  | RuleToolResult  : ev:tool_evidence        -> inference_rule
  | RuleDerivation  : ev:derivation_evidence  -> inference_rule

noeq
type inference_step = {
  premises: list string;
  rule: inference_rule;
  step_conclusion: string;
}

noeq
type inference_chain = {
  steps: list inference_step;
  final_conclusion: string;
}

(* --- Proof Witnesses --- *)

noeq
type proof_certificate = {
  pc_trace_id: string;
  pc_content_hash: string;
  pc_rule_used: inference_rule;
  pc_properties: list string;
  pc_timestamp: nat;
  pc_obs_count: nat;
}

(* --- Memory Types --- *)

noeq
type memory_entry = {
  me_key: string;
  me_content: string;
  me_source_trusted: bool;
  me_trace_id: string;
  me_proof_cert: option proof_certificate;
}

noeq
type memory_state = {
  facts: list memory_entry;
}

noeq
type domain_spec = {
  critical_patterns: list string;
  required_keys: list string;
}

noeq
type poison_patterns = {
  instruction_overrides: list string;
  role_escalations: list string;
  exfiltration_markers: list string;
}

let tier1_bound : nat = 2200
