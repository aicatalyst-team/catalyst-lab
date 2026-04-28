"""Tests for the pre-commit sensitive data scanner."""

import tempfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_spec = spec_from_file_location(
    "check_sensitive_data",
    Path(__file__).resolve().parent.parent / "scripts" / "check-sensitive-data.py",
)
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)

check_file = _mod.check_file
is_safe_ip = _mod.is_safe_ip
PATTERNS = _mod.PATTERNS


def _check_content(content: str) -> list:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        f.flush()
        return check_file(f.name)


def test_detects_ipv4_address():
    violations = _check_content("host: 10.0.0.5\n")
    assert len(violations) == 1
    assert violations[0][1] == "IPv4 address"


def test_allows_safe_ips():
    violations = _check_content("host: 127.0.0.1\nbind: 0.0.0.0\n")
    assert len(violations) == 0


def test_detects_email_address():
    violations = _check_content("contact: user@example.com\n")
    assert len(violations) == 1
    assert violations[0][1] == "email address"


def test_detects_hardcoded_password():
    violations = _check_content("password: hunter2\n")
    assert len(violations) == 1
    assert violations[0][1] == "hardcoded credential"


def test_allows_secret_key_ref():
    violations = _check_content("password: secretKeyRef\n")
    assert len(violations) == 0


def test_allows_placeholder():
    violations = _check_content("api_key: <PLACEHOLDER>\n")
    assert len(violations) == 0


def test_clean_file_passes():
    violations = _check_content("name: my-service\nport: 8080\n")
    assert len(violations) == 0
