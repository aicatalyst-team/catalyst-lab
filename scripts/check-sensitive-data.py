#!/usr/bin/env python3
"""Pre-commit hook to block sensitive data from being committed."""

import re
import sys

SAFE_IPS = {"127.0.0.1", "0.0.0.0"}

PATTERNS = [
    (
        "ipv4_address",
        re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"),
        "IPv4 address",
    ),
    (
        "email_address",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "email address",
    ),
    (
        "hardcoded_credential",
        re.compile(
            r"(?i)^\s*(?:password|passwd|api_key|secret|token)\s*:\s*(?!\s*$)"
            r"(?!\s*[\"']?\s*\$\{)"  # not ${...} interpolation
            r"(?!\s*[\"']?\s*<)"  # not <PLACEHOLDER>
            r"(?!\s*secretKeyRef\b)"  # not secretKeyRef
            r"(?!\s*configMapKeyRef\b)"  # not configMapKeyRef
            r"(?!\s*valueFrom\b)"  # not valueFrom
            r"(?!\s*\*+\s*$)"  # not masked value ***
            r"(?!\s*[\"']?\s*\n)"  # not empty value
            r".+",
            re.MULTILINE,
        ),
        "hardcoded credential",
    ),
]


def is_safe_ip(match: re.Match) -> bool:
    ip = match.group(0)
    if ip in SAFE_IPS:
        return True
    octets = [int(match.group(i)) for i in range(1, 5)]
    return any(o > 255 for o in octets)


def check_file(path: str) -> list[tuple[int, str, str]]:
    violations: list[tuple[int, str, str]] = []
    try:
        lines = open(path, encoding="utf-8", errors="replace").readlines()
    except OSError:
        return violations

    for lineno, line in enumerate(lines, 1):
        stripped = line.rstrip("\n")
        for name, pattern, label in PATTERNS:
            for match in pattern.finditer(stripped):
                if name == "ipv4_address" and is_safe_ip(match):
                    continue
                violations.append((lineno, label, stripped.strip()))
                break  # one report per pattern per line

    return violations


def main() -> int:
    files = sys.argv[1:]
    found = False
    for path in files:
        violations = check_file(path)
        for lineno, label, line in violations:
            print(f"{path}:{lineno}: {label} detected: {line[:120]}")
            found = True
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
