"""Tether Verification Gateway — gRPC server.

Wraps the five verification surfaces (P1-P10) as a gRPC service.
The proto stubs are generated at container build time; the try/except
import allows running tests and linters before code-gen.

Health endpoints on :8080 let Kubernetes probes work without gRPC
health-checking support in the load balancer.  POST /verify provides
an HTTP bridge for the Hermes memory provider plugin.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import subprocess
import threading
import time
from concurrent import futures
from http.server import BaseHTTPRequestHandler, HTTPServer

import grpc

# Proto stubs are generated at build time.  Fall back to top-level
# import so the module is still importable during local development.
try:
    from . import tether_pb2, tether_pb2_grpc
except ImportError:
    # Local development keeps generated stubs under proto/; the container
    # build copies them into src/tether/ so the package-local import wins.
    try:
        from proto import tether_pb2, tether_pb2_grpc  # type: ignore[no-redef]
    except ImportError:
        import tether_pb2
        import tether_pb2_grpc  # type: ignore[no-redef]

from .gateway_client import (
    AggregationEvidence,
    DerivationEvidence,
    DomainSpec,
    ExtractionEvidence,
    InferenceChain,
    InferenceRule,
    InferenceStep,
    MemoryEntry,
    MemoryIntent,
    MemoryState,
    Observation,
    PoisonPatterns,
    ProofCertificate,
    ProofWitness,
    RuleKind,
    SkillCode,
    SkillSpec,
    TemporalCertificate,
    TetherGatewayClient,
    ToolCallRecord,
    ToolDeclaration,
    ToolEvidence,
    TrustLevel,
    build_chain_from_proxy,
    call_within_scope,
    certificate_reverify,
    cross_agent_verify,
    extract_observations_from_messages,
    side_effects_contained,
    skill_interface_valid,
    skill_safe_to_persist,
    skill_tools_within_scope,
    tool_invocation_safe,
    witness_has_minimum_properties,
    witness_well_formed,
)
from .gateway_client import (
    ToolResult as GatewayToolResult,
)

logger = logging.getLogger("tether.server")

# ---------------------------------------------------------------------------
# Protobuf  <-->  Python dataclass converters
# ---------------------------------------------------------------------------

_TRUST_MAP: dict[int, TrustLevel] = {
    tether_pb2.DIRECT_OBSERVATION: TrustLevel.DIRECT_OBSERVATION,
    tether_pb2.TOOL_OUTPUT: TrustLevel.TOOL_OUTPUT,
    tether_pb2.EXTERNAL_INPUT: TrustLevel.EXTERNAL_INPUT,
    tether_pb2.AGENT_GENERATED: TrustLevel.AGENT_GENERATED,
    tether_pb2.UNVERIFIED: TrustLevel.UNVERIFIED,
}

_TRUST_REVERSE: dict[TrustLevel, int] = {v: k for k, v in _TRUST_MAP.items()}


def _proto_to_rule(rule_proto) -> InferenceRule:
    """Convert a protobuf InferenceRule oneof into a Python InferenceRule."""
    which = rule_proto.WhichOneof("rule")
    if which == "identity":
        return InferenceRule(kind=RuleKind.IDENTITY)
    if which == "extraction":
        ev = rule_proto.extraction
        return InferenceRule(
            kind=RuleKind.EXTRACTION,
            evidence=ExtractionEvidence(source_premise=ev.source_premise),
        )
    if which == "aggregation":
        ev = rule_proto.aggregation
        return InferenceRule(
            kind=RuleKind.AGGREGATION,
            evidence=AggregationEvidence(source_premises=list(ev.source_premises)),
        )
    if which == "tool_result":
        ev = rule_proto.tool_result
        return InferenceRule(
            kind=RuleKind.TOOL_RESULT,
            evidence=ToolEvidence(
                tool_name=ev.tool_name,
                call_id=ev.call_id,
                tool_trusted=ev.tool_trusted,
            ),
        )
    if which == "derivation":
        ev = rule_proto.derivation
        return InferenceRule(
            kind=RuleKind.DERIVATION,
            evidence=DerivationEvidence(
                domain_rule_id=ev.domain_rule_id,
            ),
        )
    # Unset oneof — default to identity (strictest rule: requires
    # conclusion == single premise, so unclassified content is maximally
    # constrained rather than silently accepted).
    return InferenceRule(kind=RuleKind.IDENTITY)


def _proto_to_observation(obs) -> Observation:
    trust = _TRUST_MAP.get(obs.trust, TrustLevel.UNVERIFIED)
    tool_call_id = obs.tool_call_id if obs.HasField("tool_call_id") else None
    return Observation(
        source=obs.source,
        content=obs.content,
        trust=trust,
        tool_call_id=tool_call_id,
    )


def _proto_to_step(step) -> InferenceStep:
    return InferenceStep(
        premises=list(step.premises),
        rule=_proto_to_rule(step.rule),
        conclusion=step.conclusion,
    )


def _proto_to_chain(chain) -> InferenceChain:
    return InferenceChain(
        steps=[_proto_to_step(s) for s in chain.steps],
        final_conclusion=chain.final_conclusion,
    )


def _proto_to_memory_entry(entry) -> MemoryEntry:
    return MemoryEntry(
        key=entry.key,
        content=entry.content,
        source_trusted=entry.source_trusted,
        trace_id=entry.trace_id,
    )


def _proto_to_poison_patterns(pp) -> PoisonPatterns:
    return PoisonPatterns(
        instruction_overrides=list(pp.instruction_overrides),
        role_escalations=list(pp.role_escalations),
        exfiltration_markers=list(pp.exfiltration_markers),
    )


def _proto_to_domain_spec(ds) -> DomainSpec:
    return DomainSpec(
        critical_patterns=list(ds.critical_patterns),
        required_keys=list(ds.required_keys),
    )


def _proto_to_skill_spec(spec) -> SkillSpec:
    return SkillSpec(
        name=spec.name,
        inputs=list(spec.inputs),
        output_type=spec.output_type,
        max_body_size=spec.max_body_size,
        allowed_tools=list(spec.allowed_tools),
    )


def _proto_to_skill_code(code) -> SkillCode:
    return SkillCode(
        name=code.name,
        body=code.body,
        declared_inputs=list(code.declared_inputs),
        declared_output=code.declared_output,
        tool_calls=list(code.tool_calls),
    )


def _proto_to_tool_decl(decl) -> ToolDeclaration:
    return ToolDeclaration(
        name=decl.name,
        allowed_args=list(decl.allowed_args),
        output_type=decl.output_type,
        side_effects=list(decl.declared_side_effects),
    )


def _proto_to_tool_call(call) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name=call.tool_name,
        arguments=list(call.arguments),
    )


def _proto_to_tool_result(result) -> GatewayToolResult:
    return GatewayToolResult(
        output=result.output,
        observed_side_effects=list(result.observed_side_effects),
    )


def _proto_to_proof_witness(w) -> ProofWitness:
    return ProofWitness(
        source_agent=w.source_agent,
        content_hash=w.content_hash,
        rule_used=_proto_to_rule(w.rule_used),
        properties=list(w.properties),
        obs_count=w.observation_count,
        source_trusted=w.source_trusted,
    )


def _rule_to_proto(rule: InferenceRule):
    """Convert a Python InferenceRule to a protobuf InferenceRule."""
    proto = tether_pb2.InferenceRule()
    if rule.kind == RuleKind.IDENTITY:
        proto.identity.CopyFrom(tether_pb2.IdentityRule())
    elif rule.kind == RuleKind.EXTRACTION and rule.evidence:
        proto.extraction.CopyFrom(
            tether_pb2.ExtractionRule(source_premise=rule.evidence.source_premise)
        )
    elif rule.kind == RuleKind.AGGREGATION and rule.evidence:
        proto.aggregation.CopyFrom(
            tether_pb2.AggregationRule(source_premises=rule.evidence.source_premises)
        )
    elif rule.kind == RuleKind.TOOL_RESULT and rule.evidence:
        proto.tool_result.CopyFrom(
            tether_pb2.ToolResultRule(
                tool_name=rule.evidence.tool_name,
                call_id=rule.evidence.call_id,
                tool_trusted=rule.evidence.tool_trusted,
            )
        )
    elif rule.kind == RuleKind.DERIVATION and rule.evidence:
        proto.derivation.CopyFrom(
            tether_pb2.DerivationRule(
                domain_rule_id=rule.evidence.domain_rule_id,
            )
        )
    return proto


def _cert_to_proto(cert: ProofCertificate):
    """Convert a Python ProofCertificate to a protobuf ProofCertificate."""
    return tether_pb2.ProofCertificate(
        trace_id=cert.trace_id,
        content_hash=cert.content_hash,
        rule_used=_rule_to_proto(cert.rule_used),
        properties_satisfied=cert.properties_satisfied,
        timestamp=cert.timestamp,
        observation_count=cert.obs_count,
    )


# ---------------------------------------------------------------------------
# gRPC Servicer
# ---------------------------------------------------------------------------


class TetherGatewayServicer(tether_pb2_grpc.TetherGatewayServicer):
    """Implements all six verification RPCs plus health."""

    def __init__(self):
        self._client = TetherGatewayClient()
        logger.info("TetherGatewayServicer initialized")

    # -- Composed pipeline (Surface 1-5) --

    def VerifyWrite(self, request, context):
        logger.debug("VerifyWrite trace_id=%s", request.trace_id)

        observations = [_proto_to_observation(o) for o in request.observations]
        chain = _proto_to_chain(request.chain)
        conclusion = _proto_to_memory_entry(request.entry)
        existing = MemoryState(facts=[_proto_to_memory_entry(m) for m in request.existing_memory])
        poison_patterns = _proto_to_poison_patterns(request.poison_patterns)
        domain_spec = _proto_to_domain_spec(request.domain_spec)

        intent = MemoryIntent(
            agent_id=request.trace_id,
            observations=observations,
            chain=chain,
            conclusion=conclusion,
            existing=existing,
            bound=request.tier1_bound,
            poison_patterns=poison_patterns,
            domain_spec=domain_spec,
        )

        t0 = time.monotonic()
        result = self._client.verify_write(intent)
        latency_ms = (time.monotonic() - t0) * 1000

        resp = tether_pb2.VerifyWriteResponse(
            properties_satisfied=result.properties_satisfied,
        )

        if result.result.value == "WriteOk":
            resp.status = tether_pb2.VerifyWriteResponse.WRITE_OK
            if result.certificate:
                resp.certificate.CopyFrom(_cert_to_proto(result.certificate))
        else:
            resp.status = tether_pb2.VerifyWriteResponse.WRITE_REJECTED
            resp.violations.append(result.result.value)

        _store_certificate(request.trace_id, result, result.certificate, latency_ms)
        _log_to_mlflow(request.trace_id, result, result.certificate, latency_ms)

        return resp

    # -- Surface 1: Inference chain soundness --

    def VerifyInference(self, request, context):
        logger.debug("VerifyInference trace_id=%s", request.trace_id)

        chain = _proto_to_chain(request.chain)
        observations = [_proto_to_observation(o) for o in request.observations]
        obs_contents = [o.content for o in observations]

        from .gateway_client import _chain_well_formed

        valid = _chain_well_formed(obs_contents, chain)

        properties = []
        violations = []
        if valid:
            properties.append("P1:inference_sound")
        else:
            violations.append("P1:chain_not_well_formed")

        return tether_pb2.VerifyInferenceResponse(
            valid=valid,
            properties_satisfied=properties,
            violations=violations,
        )

    # -- Surface 2: Skill verification --

    def VerifySkill(self, request, context):
        logger.debug("VerifySkill trace_id=%s", request.trace_id)

        spec = _proto_to_skill_spec(request.spec)
        code = _proto_to_skill_code(request.code)
        pp = _proto_to_poison_patterns(request.poison_patterns)

        iface_valid = skill_interface_valid(spec, code)
        tools_ok = skill_tools_within_scope(spec, code)
        from .gateway_client import _content_safe

        content_ok = _content_safe(code.body, pp)
        safe = skill_safe_to_persist(spec, code, pp)

        violations = []
        if not iface_valid:
            violations.append("interface_mismatch")
        if not tools_ok:
            violations.append("unauthorized_tool_call")
        if not content_ok:
            violations.append("poisoned_content")

        return tether_pb2.VerifySkillResponse(
            safe_to_persist=safe,
            interface_valid=iface_valid,
            tools_within_scope=tools_ok,
            content_safe=content_ok,
            violations=violations,
        )

    # -- Surface 3: Tool invocation trust --

    def VerifyToolInvocation(self, request, context):
        logger.debug("VerifyToolInvocation trace_id=%s", request.trace_id)

        decl = _proto_to_tool_decl(request.declaration)
        call = _proto_to_tool_call(request.call)
        result = _proto_to_tool_result(request.result)

        scope_ok = call_within_scope(decl, call)
        effects_ok = side_effects_contained(decl, call, result)
        safe = tool_invocation_safe(decl, call, result)

        violations = []
        if not scope_ok:
            violations.append("P9:call_outside_scope")
        if not effects_ok:
            violations.append("P10:undeclared_side_effects")

        return tether_pb2.VerifyToolInvocationResponse(
            safe=safe,
            call_within_scope=scope_ok,
            side_effects_contained=effects_ok,
            violations=violations,
        )

    # -- Surface 4: Temporal validity --

    def VerifyTemporal(self, request, context):
        logger.debug("VerifyTemporal trace_id=%s", request.trace_id)

        cert_proto = request.certificate
        cert = ProofCertificate(
            trace_id=cert_proto.trace_id,
            content_hash=cert_proto.content_hash,
            rule_used=_proto_to_rule(cert_proto.rule_used),
            properties_satisfied=list(cert_proto.properties_satisfied),
            timestamp=cert_proto.timestamp,
            obs_count=cert_proto.observation_count,
        )

        tc = TemporalCertificate(
            cert=cert,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
        )

        valid = certificate_reverify(tc, request.stored_content_hash, request.current_time)

        from .gateway_client import certificate_content_matches, certificate_valid_at

        in_window = certificate_valid_at(tc, request.current_time)
        content_ok = certificate_content_matches(cert, request.stored_content_hash)

        violations = []
        if not in_window:
            violations.append("certificate_expired")
        if not content_ok:
            violations.append("content_hash_mismatch")

        return tether_pb2.VerifyTemporalResponse(
            valid=valid,
            within_time_window=in_window,
            content_matches=content_ok,
            violations=violations,
        )

    # -- Surface 5: Proof witness transport --

    def VerifyWitness(self, request, context):
        logger.debug("VerifyWitness trace_id=%s", request.trace_id)

        witness = _proto_to_proof_witness(request.witness)

        wf = witness_well_formed(witness)
        content_ok = cross_agent_verify(witness, request.stored_content_hash)
        props_ok = witness_has_minimum_properties(witness, list(request.required_properties))
        valid = wf and content_ok and props_ok

        violations = []
        if not wf:
            violations.append("witness_malformed")
        if not content_ok:
            violations.append("content_hash_mismatch")
        if not props_ok:
            violations.append("missing_required_properties")

        return tether_pb2.VerifyWitnessResponse(
            valid=valid,
            well_formed=wf,
            content_matches=content_ok if wf else False,
            has_required_properties=props_ok,
            violations=violations,
        )

    # -- Health --

    def Health(self, request, context):
        return tether_pb2.HealthResponse(
            healthy=True,
            fstar_version=_detect_fstar_version(),
            z3_version=_detect_z3_version(),
            specs_loaded=0,
        )


def _detect_fstar_version() -> str:
    fstar = os.path.join(os.environ.get("FSTAR_HOME", "/opt/fstar"), "bin", "fstar.exe")
    try:
        r = subprocess.run([fstar, "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split("\n")[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "python-mirror"


def _detect_z3_version() -> str:
    z3 = os.environ.get("Z3_PATH", "/usr/local/bin/z3")
    try:
        r = subprocess.run([z3, "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split("\n")[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "python-mirror"


# ---------------------------------------------------------------------------
# PostgreSQL certificate storage (optional)
# ---------------------------------------------------------------------------

_db_pool = None


def _setup_db():
    """Create a psycopg2 connection pool from TETHER_DB_* env vars.

    Retries up to 3 times to handle Istio sidecar startup races.
    """
    global _db_pool
    host = os.environ.get("TETHER_DB_HOST")
    if not host:
        logger.info("TETHER_DB_HOST not set — certificate storage disabled")
        return None

    try:
        import psycopg2
        import psycopg2.pool
    except ImportError:
        logger.warning("psycopg2 not installed — certificate storage disabled")
        return None

    for attempt in range(3):
        try:
            _db_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                host=host,
                port=int(os.environ.get("TETHER_DB_PORT", "5432")),
                dbname=os.environ.get("TETHER_DB_NAME", "tetherdb"),
                user=os.environ.get("TETHER_DB_USER", "tether"),
                password=os.environ.get("TETHER_DB_PASSWORD", ""),
                connect_timeout=5,
            )
            logger.info(
                "PostgreSQL certificate storage enabled — %s:%s/%s",
                host,
                os.environ.get("TETHER_DB_PORT", "5432"),
                os.environ.get("TETHER_DB_NAME", "tetherdb"),
            )
            return _db_pool
        except Exception as exc:
            if attempt < 2:
                logger.info(
                    "PostgreSQL connection attempt %d failed, retrying: %s", attempt + 1, exc
                )
                time.sleep(2)
            else:
                logger.warning("PostgreSQL connection failed after 3 attempts: %s", exc)
    return None


def _store_certificate(trace_id, result, certificate, latency_ms=0):
    """Persist a verification result to PostgreSQL."""
    if _db_pool is None:
        return
    conn = None
    try:
        conn = _db_pool.getconn()
        with conn.cursor() as cur:
            status = "WRITE_OK" if result.result.value == "WriteOk" else "WRITE_REJECTED"
            violations = [result.result.value] if status == "WRITE_REJECTED" else []
            cert_hash = certificate.content_hash if certificate else ""
            rule_used = ""
            if certificate and certificate.rule_used:
                rule_used = (
                    certificate.rule_used.kind.name
                    if hasattr(certificate.rule_used, "kind")
                    else str(certificate.rule_used)
                )
            cur.execute(
                """INSERT INTO proof_certificates
                   (trace_id, content_hash, rule_used, properties, obs_count, status, violations)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    trace_id,
                    cert_hash,
                    rule_used,
                    list(result.properties_satisfied),
                    certificate.obs_count if certificate else 0,
                    status,
                    violations,
                ),
            )
        conn.commit()
    except Exception as exc:
        logger.debug("Certificate store failed: %s", exc)
        if conn:
            conn.rollback()
    finally:
        if conn:
            _db_pool.putconn(conn)


# ---------------------------------------------------------------------------
# MLflow audit trail (optional)
# ---------------------------------------------------------------------------

_mlflow_enabled = False


def _setup_mlflow():
    """Configure MLflow tracking if MLFLOW_TRACKING_URI is set.

    Defers experiment creation to first use to avoid blocking startup
    if the MLflow server is not yet ready.
    """
    global _mlflow_enabled
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        logger.info("MLFLOW_TRACKING_URI not set — audit trail disabled")
        return

    try:
        import mlflow  # noqa: F401

        mlflow.set_tracking_uri(uri)
        _mlflow_enabled = True
        logger.info("MLflow audit trail enabled — %s", uri)
    except ImportError:
        logger.warning("mlflow not installed — audit trail disabled")
    except Exception as exc:
        logger.warning("MLflow setup failed: %s", exc)


_mlflow_experiment_set = False


def _log_to_mlflow(trace_id, result, certificate, latency_ms):
    """Log a verification result as an MLflow run."""
    global _mlflow_experiment_set
    if not _mlflow_enabled:
        return
    try:
        import mlflow

        if not _mlflow_experiment_set:
            mlflow.set_experiment("tether-verification")
            _mlflow_experiment_set = True
        status = "WRITE_OK" if result.result.value == "WriteOk" else "WRITE_REJECTED"
        rule_used = ""
        if certificate and certificate.rule_used:
            rule_used = (
                certificate.rule_used.kind.name
                if hasattr(certificate.rule_used, "kind")
                else str(certificate.rule_used)
            )
        with mlflow.start_run(run_name=f"verify-{trace_id[:12]}"):
            mlflow.log_params(
                {
                    "trace_id": trace_id,
                    "status": status,
                    "rule_used": rule_used,
                }
            )
            mlflow.log_metrics(
                {
                    "latency_ms": latency_ms,
                    "obs_count": certificate.obs_count if certificate else 0,
                    "properties_count": len(result.properties_satisfied),
                }
            )
            mlflow.set_tags(
                {
                    "properties": ",".join(result.properties_satisfied),
                    "violations": ",".join(
                        [result.result.value] if status == "WRITE_REJECTED" else []
                    ),
                }
            )
    except Exception as exc:
        logger.debug("MLflow log failed: %s", exc)


# ---------------------------------------------------------------------------
# HTTP health server (for K8s probes that don't speak gRPC)
# ---------------------------------------------------------------------------

_healthy = threading.Event()


_gateway_client = None


class _HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for /healthz, /readyz, and POST /verify.

    POST /verify is the HTTP bridge for the Hermes memory provider plugin.
    """

    def do_GET(self):
        if self.path in ("/healthz", "/readyz"):
            if _healthy.is_set():
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"not ready")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/verify":
            self.send_response(404)
            self.end_headers()
            return
        self._handle_verify()

    def _handle_verify(self):
        """HTTP bridge: accept JSON, run verification, return result."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, ValueError):
            self._json_response(400, {"error": "invalid JSON"})
            return

        content = body.get("content", "")
        observation = body.get("observation", content)
        trace_id = body.get("trace_id", f"http-{hashlib.sha256(content.encode()).hexdigest()[:12]}")
        action = body.get("action", "add")
        target = body.get("target", "memory")

        # Trust derivation: callers must explicitly assert trust.
        # Default is secure (untrusted) — matches F* spec where
        # me_source_trusted and obs_trust are independent parameters.
        source_trusted = body.get("source_trusted", False)
        obs_trust_name = body.get("observation_trust", "ExternalInput")
        _TRUST_NAME_MAP = {t.value: t for t in TrustLevel}
        obs_trust = _TRUST_NAME_MAP.get(obs_trust_name, TrustLevel.UNVERIFIED)

        if not content:
            self._json_response(400, {"error": "content is required"})
            return

        if _gateway_client is None:
            self._json_response(503, {"error": "gateway not ready"})
            return

        entry = MemoryEntry(
            key=target,
            content=content,
            source_trusted=source_trusted,
            trace_id=trace_id,
        )
        chain = InferenceChain(
            steps=[
                InferenceStep(
                    premises=[observation],
                    rule=InferenceRule(kind=RuleKind.IDENTITY),
                    conclusion=content,
                )
            ],
            final_conclusion=content,
        )
        observations = [
            Observation(
                source="hermes-agent",
                content=observation,
                trust=obs_trust,
            )
        ]
        poison_patterns = PoisonPatterns(
            instruction_overrides=[
                "ignore previous instructions",
                "ignore all previous",
                "disregard your instructions",
                "override your system prompt",
            ],
            role_escalations=[
                "you are now",
                "act as root",
                "switch to admin mode",
            ],
            exfiltration_markers=[
                "dump all stored",
                "export all data",
                "exfiltrate",
            ],
        )

        intent = MemoryIntent(
            agent_id=trace_id,
            observations=observations,
            chain=chain,
            conclusion=entry,
            existing=MemoryState(facts=[]),
            bound=2200,
            poison_patterns=poison_patterns,
            domain_spec=DomainSpec(required_keys=[target]),
        )

        t0 = time.monotonic()
        result = _gateway_client.verify_write(intent)
        latency_ms = (time.monotonic() - t0) * 1000

        _store_certificate(trace_id, result, result.certificate, latency_ms)
        _log_to_mlflow(trace_id, result, result.certificate, latency_ms)

        status = "WRITE_OK" if result.result.value == "WriteOk" else "WRITE_REJECTED"
        resp_body = {
            "status": status,
            "action": action,
            "target": target,
            "properties": list(result.properties_satisfied),
            "latency_ms": round(latency_ms, 2),
        }
        if result.certificate:
            resp_body["certificate"] = {
                "trace_id": result.certificate.trace_id,
                "content_hash": result.certificate.content_hash,
                "properties": list(result.certificate.properties_satisfied),
                "obs_count": result.certificate.obs_count,
            }
        if status == "WRITE_REJECTED":
            resp_body["violations"] = [result.result.value]

        logger.info(
            "HTTP /verify trace_id=%s status=%s latency=%.1fms", trace_id, status, latency_ms
        )
        self._json_response(200, resp_body)

    def _json_response(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        return


def _run_health_server(port: int = 8080) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("HTTP health server listening on :%d", port)
    return server


# ---------------------------------------------------------------------------
# Inference proxy (TETHER_MODE=inference-proxy)
# ---------------------------------------------------------------------------

_PROXY_PORT = int(os.environ.get("TETHER_PROXY_PORT", "8082"))
_LLM_UPSTREAM = os.environ.get("TETHER_LLM_UPSTREAM", "")
_PROXY_ENFORCE = os.environ.get("TETHER_ENFORCE", "false").lower() in ("true", "1", "yes")
_PROXY_SOURCE_TRUSTED = os.environ.get("TETHER_SOURCE_TRUSTED", "true").lower() in (
    "true",
    "1",
    "yes",
)

_upstream_client = None

_DEFAULT_POISON_PATTERNS = PoisonPatterns(
    instruction_overrides=[
        "ignore previous instructions",
        "ignore all previous",
        "disregard your instructions",
        "override your system prompt",
    ],
    role_escalations=[
        "you are now",
        "act as root",
        "switch to admin mode",
    ],
    exfiltration_markers=[
        "dump all stored",
        "export all data",
        "exfiltrate",
    ],
)

_MEMORY_TAG_PATTERN = None


def _compile_memory_tag_pattern():
    global _MEMORY_TAG_PATTERN
    import re

    _MEMORY_TAG_PATTERN = re.compile(
        r"<memory[_\s]?\w*[^>]*>(.*?)</memory[_\s]?\w*>",
        re.DOTALL,
    )


def _extract_memory_candidates(response_content: str) -> list[str]:
    """Extract content that may become memory writes from an LLM response."""
    if _MEMORY_TAG_PATTERN is None:
        _compile_memory_tag_pattern()
    matches = _MEMORY_TAG_PATTERN.findall(response_content)
    if matches:
        return [m.strip() for m in matches if m.strip()]
    return [response_content.strip()] if response_content.strip() else []


class _InferenceProxyHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible reverse proxy that captures observations and verifies.

    Sits between the agent and RHOAI KServe model serving. Extracts
    observations from the prompt messages, classifies the inference rule
    automatically, and verifies before relaying the response.
    """

    def do_GET(self):
        if self.path in ("/healthz", "/readyz"):
            if _healthy.is_set():
                self._json_response(200, {"status": "ok", "mode": "inference-proxy"})
            else:
                self._json_response(503, {"status": "not ready"})
        elif self.path.startswith("/v1/"):
            self._passthrough("GET")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            self._handle_chat_completions()
        elif self.path.startswith("/v1/"):
            self._passthrough("POST")
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_chat_completions(self):
        """Main proxy handler: capture observations, forward, classify, verify."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length) if length else b"{}"
            request_body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            self._json_response(400, {"error": "invalid JSON"})
            return

        if _upstream_client is None:
            self._json_response(503, {"error": "upstream not configured"})
            return

        messages = request_body.get("messages", [])
        observations = extract_observations_from_messages(messages)
        trace_id = f"proxy-{hashlib.sha256(raw_body).hexdigest()[:12]}"

        try:
            upstream_resp = _upstream_client.post(
                "/chat/completions",
                content=raw_body,
                headers={"Content-Type": "application/json"},
            )
            upstream_status = upstream_resp.status_code
            upstream_body = upstream_resp.content
        except Exception as exc:
            logger.error("Upstream LLM call failed: %s", exc)
            self._json_response(502, {"error": f"upstream error: {exc}"})
            return

        try:
            response_json = json.loads(upstream_body)
        except json.JSONDecodeError:
            self._relay_raw(upstream_status, upstream_body)
            return

        choices = response_json.get("choices", [])
        if not choices:
            self._relay_raw(upstream_status, upstream_body)
            return

        response_content = ""
        msg = choices[0].get("message", {})
        response_content = msg.get("content") or ""

        candidates = _extract_memory_candidates(response_content)

        verification_results = []
        for candidate in candidates:
            chain = build_chain_from_proxy(observations, candidate)
            rule_used = chain.steps[0].rule if chain.steps else None

            entry = MemoryEntry(
                key="proxy-observed",
                content=candidate,
                source_trusted=_PROXY_SOURCE_TRUSTED,
                trace_id=trace_id,
            )
            intent = MemoryIntent(
                agent_id=trace_id,
                observations=observations,
                chain=chain,
                conclusion=entry,
                existing=MemoryState(facts=[]),
                bound=2200,
                poison_patterns=_DEFAULT_POISON_PATTERNS,
                domain_spec=DomainSpec(required_keys=["proxy-observed"]),
            )

            t0 = time.monotonic()
            result = _gateway_client.verify_write(intent)
            latency_ms = (time.monotonic() - t0) * 1000

            _store_certificate(trace_id, result, result.certificate, latency_ms)
            _log_to_mlflow(trace_id, result, result.certificate, latency_ms)
            _store_proxy_verification(
                trace_id,
                raw_body,
                rule_used,
                len(observations),
                result.result.value,
                candidate,
            )

            status = "WRITE_OK" if result.result.value == "WriteOk" else "WRITE_REJECTED"
            verification_results.append(
                {
                    "rule": rule_used.kind.value if rule_used else "unknown",
                    "status": status,
                    "properties": list(result.properties_satisfied),
                }
            )

            logger.info(
                "Proxy verify trace=%s rule=%s status=%s obs=%d latency=%.1fms",
                trace_id,
                rule_used.kind.value if rule_used else "unknown",
                status,
                len(observations),
                latency_ms,
            )

        any_rejected = any(r["status"] == "WRITE_REJECTED" for r in verification_results)

        if _PROXY_ENFORCE and any_rejected:
            all_gates = ["P1", "P2", "P3", "P4", "P5", "P6"]
            failed_props = []
            for r in verification_results:
                if r["status"] == "WRITE_REJECTED":
                    passed = {prop.split(":")[0] for prop in r.get("properties", [])}
                    failed_props.extend(g for g in all_gates if g not in passed)
            rejection_body = json.dumps(
                {
                    "id": response_json.get("id", ""),
                    "object": "chat.completion",
                    "model": response_json.get("model", ""),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "[Tether] Response blocked: verification failed. "
                                f"Failed gates: "
                                f"{', '.join(sorted(set(failed_props))) or 'unknown'}.",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Tether-Status", "WRITE_REJECTED")
            self.send_header("X-Tether-Enforce", "true")
            if verification_results:
                self.send_header("X-Tether-Rule", verification_results[0]["rule"])
            self.send_header("X-Tether-Obs-Count", str(len(observations)))
            self.end_headers()
            self.wfile.write(rejection_body)
            logger.warning(
                "Proxy ENFORCED rejection trace=%s failed_gates=%s",
                trace_id,
                ",".join(sorted(set(failed_props))),
            )
            return

        self.send_response(upstream_status)
        self.send_header("Content-Type", "application/json")
        if verification_results:
            top = verification_results[0]
            self.send_header("X-Tether-Rule", top["rule"])
            self.send_header("X-Tether-Status", top["status"])
            self.send_header("X-Tether-Obs-Count", str(len(observations)))
        self.end_headers()
        self.wfile.write(upstream_body)

    def _passthrough(self, method: str):
        """Forward non-chat-completion requests to upstream unchanged."""
        if _upstream_client is None:
            self._json_response(503, {"error": "upstream not configured"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else None

            path = self.path
            if path.startswith("/v1/"):
                path = "/" + path[len("/v1/") :]

            if method == "GET":
                resp = _upstream_client.get(path)
            else:
                resp = _upstream_client.post(
                    path,
                    content=body,
                    headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
                )

            self.send_response(resp.status_code)
            for key, val in resp.headers.items():
                if key.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                    self.send_header(key, val)
            self.end_headers()
            self.wfile.write(resp.content)
        except Exception as exc:
            logger.error("Passthrough failed: %s", exc)
            self._json_response(502, {"error": str(exc)})

    def _relay_raw(self, status_code: int, body: bytes):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        return


def _store_proxy_verification(
    trace_id: str,
    request_body: bytes,
    rule_used,
    obs_count: int,
    status: str,
    conclusion_preview: str,
):
    """Store proxy verification result in PostgreSQL."""
    if _db_pool is None:
        return
    try:
        conn = _db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO proxy_verifications
                       (trace_id, request_hash, classified_rule, obs_count,
                        status, conclusion_preview)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        trace_id,
                        hashlib.sha256(request_body).hexdigest(),
                        rule_used.kind.value if rule_used else "unknown",
                        obs_count,
                        status,
                        conclusion_preview[:500],
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            _db_pool.putconn(conn)
    except Exception as exc:
        logger.debug("Failed to store proxy verification: %s", exc)


def _run_inference_proxy(port: int = 8082) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), _InferenceProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Inference proxy listening on :%d", port)
    return server


# ---------------------------------------------------------------------------
# OTel bootstrap (optional)
# ---------------------------------------------------------------------------


def _setup_otel():
    """Configure OpenTelemetry gRPC interceptor if the env var is set."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled")
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "tether-gateway"})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("OTel tracing enabled — exporting to %s", endpoint)
        return provider
    except ImportError:
        logger.warning(
            "OTel packages not installed — tracing disabled "
            "(install opentelemetry-sdk and opentelemetry-exporter-otlp-proto-grpc)"
        )
        return None


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

_GRPC_PORT = int(os.environ.get("TETHER_GRPC_PORT", "50051"))
_HEALTH_PORT = int(os.environ.get("TETHER_HEALTH_PORT", "8080"))
_TETHER_MODE = os.environ.get("TETHER_MODE", "gateway")


def _init_upstream_client():
    """Initialize the httpx client for the upstream LLM (KServe)."""
    global _upstream_client
    if not _LLM_UPSTREAM:
        logger.error("TETHER_LLM_UPSTREAM not set — proxy cannot forward requests")
        return
    try:
        import httpx

        ssl_cert = os.environ.get("SSL_CERT_FILE")
        verify = ssl_cert if ssl_cert and os.path.exists(ssl_cert) else True
        _upstream_client = httpx.Client(
            base_url=_LLM_UPSTREAM,
            verify=verify,
            timeout=120.0,
        )
        logger.info("Upstream LLM client configured: %s", _LLM_UPSTREAM)
    except ImportError:
        logger.error("httpx not installed — proxy mode requires httpx>=0.27")


def serve():
    """Start the Tether server in the configured mode."""
    global _gateway_client

    log_level = os.environ.get("TETHER_LOG_LEVEL", "info").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    logger.info("Starting Tether — mode=%s", _TETHER_MODE)

    _setup_otel()
    _setup_db()
    _setup_mlflow()

    _gateway_client = TetherGatewayClient()

    stop_event = threading.Event()
    servers_to_stop = []

    if _TETHER_MODE == "inference-proxy":
        _init_upstream_client()
        proxy_server = _run_inference_proxy(_PROXY_PORT)
        servers_to_stop.append(proxy_server)
        _healthy.set()
        logger.info("Tether Inference Proxy ready on :%d → %s", _PROXY_PORT, _LLM_UPSTREAM)
    else:
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        tether_pb2_grpc.add_TetherGatewayServicer_to_server(TetherGatewayServicer(), server)
        server.add_insecure_port(f"[::]:{_GRPC_PORT}")
        server.start()
        logger.info("gRPC server listening on :%d", _GRPC_PORT)

        health_server = _run_health_server(_HEALTH_PORT)
        servers_to_stop.append(health_server)
        _healthy.set()
        logger.info("Tether Gateway ready")

    def _handle_signal(signum, frame):
        logger.info("Received signal %d — shutting down", signum)
        _healthy.clear()
        if _TETHER_MODE != "inference-proxy":
            server.stop(grace=5)
        for s in servers_to_stop:
            s.shutdown()
        if _upstream_client is not None:
            _upstream_client.close()
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    stop_event.wait()
    logger.info("Tether stopped")


if __name__ == "__main__":
    serve()
