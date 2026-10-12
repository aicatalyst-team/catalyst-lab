"""Tether verification memory provider for Hermes.

Routes every memory write through the Tether verification sidecar
(HTTP POST to localhost:8081/verify) before the write persists. The
sidecar runs the full P1-P7 property pipeline and issues a proof
certificate for valid writes.

This plugin uses the on_memory_write() notification hook — writes are
not blocked, but every write is verified and the result is logged.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

_SIDECAR_URL = os.environ.get("TETHER_SIDECAR_URL", "http://localhost:8081/verify")


def register_memory_provider():
    return TetherMemoryProvider()


class TetherMemoryProvider(MemoryProvider):
    """Memory provider that verifies writes via the Tether sidecar."""

    def __init__(self):
        super().__init__()
        self._session_id = None

    @property
    def name(self) -> str:
        return "tether"

    def is_available(self) -> bool:
        try:
            import httpx  # noqa: F401 pylint: disable=unused-import

            return True
        except ImportError:
            return False

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        logger.info("Tether verification provider initialized (session=%s)", session_id)

    def system_prompt_block(self) -> str:
        return (
            "[Tether] All memory writes are verified by the Tether formal "
            "verification sidecar. Writes that fail verification (hallucination, "
            "contradiction, prompt injection) are flagged with proof certificates."
        )

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            import httpx

            trace_id = f"hermes-{uuid.uuid4().hex[:12]}"
            payload = {
                "action": action,
                "target": target,
                "content": content,
                "trace_id": trace_id,
            }
            if metadata:
                payload["metadata"] = {k: str(v) for k, v in metadata.items() if isinstance(k, str)}

            resp = httpx.post(_SIDECAR_URL, json=payload, timeout=10.0)
            result = resp.json()

            status = result.get("status", "UNKNOWN")
            props = result.get("properties", [])

            if status == "WRITE_OK":
                logger.info(
                    "Tether VERIFIED write: action=%s target=%s trace=%s props=%s",
                    action,
                    target,
                    trace_id,
                    props,
                )
            else:
                violations = result.get("violations", [])
                logger.warning(
                    "Tether FLAGGED write: action=%s target=%s trace=%s violations=%s",
                    action,
                    target,
                    trace_id,
                    violations,
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("Tether sidecar call failed: %s", exc)
