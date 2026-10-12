"""Subprocess wrapper for fstar.exe verification."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

FSTAR_HOME = Path(os.environ.get("FSTAR_HOME", Path.home() / ".local" / "fstar"))
FSTAR_EXE = FSTAR_HOME / "bin" / "fstar.exe"

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = PROJECT_DIR / "specs"


@dataclass(frozen=True)
class VerifyResult:
    file: str
    success: bool
    stdout: str
    stderr: str
    returncode: int


def verify_file(fst_path: str | Path, timeout: int = 120) -> VerifyResult:
    fst_path = Path(fst_path)
    cmd = [
        str(FSTAR_EXE),
        "--include",
        str(SPECS_DIR / "content"),
        "--include",
        str(SPECS_DIR / "substrate"),
        "--include",
        str(SPECS_DIR),
        str(fst_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SPECS_DIR),
    )
    return VerifyResult(
        file=str(fst_path),
        success=result.returncode == 0,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )


def verify_all(timeout_per_file: int = 120) -> list[VerifyResult]:
    files = [
        SPECS_DIR / "content" / "TetherTypes.fst",
        SPECS_DIR / "content" / "TetherPredicates.fst",
        SPECS_DIR / "content" / "PoisonDetection.fsti",
        SPECS_DIR / "content" / "PoisonDetection.fst",
        SPECS_DIR / "content" / "CompletenessCheck.fsti",
        SPECS_DIR / "content" / "CompletenessCheck.fst",
        SPECS_DIR / "content" / "AgentReasoning.fsti",
        SPECS_DIR / "content" / "AgentReasoning.fst",
        SPECS_DIR / "content" / "SkillVerification.fsti",
        SPECS_DIR / "content" / "SkillVerification.fst",
        SPECS_DIR / "content" / "TemporalValidity.fsti",
        SPECS_DIR / "content" / "TemporalValidity.fst",
        SPECS_DIR / "content" / "TetherNormTests.fst",
        SPECS_DIR / "content" / "TetherLemmas.fst",
        SPECS_DIR / "substrate" / "AgentState.fsti",
        SPECS_DIR / "substrate" / "AgentState.fst",
        SPECS_DIR / "substrate" / "ToolScope.fsti",
        SPECS_DIR / "substrate" / "ToolScope.fst",
        SPECS_DIR / "substrate" / "ProofTransport.fsti",
        SPECS_DIR / "substrate" / "ProofTransport.fst",
        SPECS_DIR / "VerifiedWrite.fst",
        SPECS_DIR / "VerifiedSkillWrite.fst",
    ]
    return [verify_file(f, timeout_per_file) for f in files]
