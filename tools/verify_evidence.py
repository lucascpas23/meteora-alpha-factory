#!/usr/bin/env python3
"""Public evidence validator for Meteora Alpha Factory.

This utility validates only sanitized, public evidence artifacts. It does not
contain strategy thresholds, pool-selection logic, custody code, private keys,
API credentials, transaction signing, or live execution instructions.

Checks:
  1. JSON Schema conformance.
  2. Cross-field semantic invariants for the public H1C9/H1C11 evidence.
  3. SHA-256 integrity for evidence files listed in evidence/SHA256SUMS.txt.
  4. A small denylist for secret-like field names in public JSON evidence.

Exit code 0 means every enabled check passed; non-zero means at least one check
failed. No network access is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - explicit CLI error path
    Draft202012Validator = None  # type: ignore[assignment]

VERSION = "0.1.0"
SUPPORTED_PHASES = {
    "H1C9_MULTI_WITNESS_FINALITY_SCOUT",
    "H1C11_TPLUS600_FRESH_FORWARD_RECORDER",
}
SECRET_FIELD_RE = re.compile(
    r"(?:private[_-]?key|secret(?:[_-]?key)?|seed(?:[_-]?phrase)?|mnemonic|api[_-]?key|bearer[_-]?token|access[_-]?token)",
    re.IGNORECASE,
)
SHA_LINE_RE = re.compile(r"^([0-9a-fA-F]{64})\s+(.+?)\s*$")


@dataclass
class CheckResult:
    status: str
    check: str
    subject: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def walk_key_paths(value: Any, prefix: str = "$") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            yield path
            yield from walk_key_paths(child, path)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from walk_key_paths(child, f"{prefix}[{idx}]")


def validate_secret_field_names(data: Any, subject: str) -> list[CheckResult]:
    hits = []
    for key_path in walk_key_paths(data):
        field = key_path.rsplit(".", 1)[-1]
        if SECRET_FIELD_RE.search(field):
            hits.append(key_path)
    if hits:
        return [CheckResult("FAIL", "public-secret-surface", subject, ", ".join(hits))]
    return [CheckResult("PASS", "public-secret-surface", subject, "no secret-like field names")]


def validate_schema(data: Any, schema: Any, subject: str) -> list[CheckResult]:
    if Draft202012Validator is None:
        return [
            CheckResult(
                "FAIL",
                "json-schema",
                subject,
                "jsonschema is not installed; run: python -m pip install -r requirements-dev.txt",
            )
        ]
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if not errors:
        return [CheckResult("PASS", "json-schema", subject, "draft 2020-12")]
    detail_parts = []
    for err in errors[:8]:
        where = "$" + "".join(f"[{item!r}]" if isinstance(item, int) else f".{item}" for item in err.absolute_path)
        detail_parts.append(f"{where}: {err.message}")
    if len(errors) > 8:
        detail_parts.append(f"... {len(errors) - 8} additional schema error(s)")
    return [CheckResult("FAIL", "json-schema", subject, " | ".join(detail_parts))]


def parse_ratio(text: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)/(\d+)", text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def candidate_offsets_h1c9(data: dict[str, Any]) -> list[int]:
    target = int(data["target_hours"])
    candidates: list[int] = []
    for offset_text, row in data["aggregate"].items():
        offset = int(offset_text)
        if (
            row["hours"] == target
            and row["ohlc_stable"] == target
            and row["decision_parity"] == target
            and row["future_input_violations"] == 0
        ):
            candidates.append(offset)
    return sorted(candidates)


def validate_semantics(data: dict[str, Any], subject: str) -> list[CheckResult]:
    phase = data.get("phase")
    failures: list[str] = []

    if phase not in SUPPORTED_PHASES:
        return [CheckResult("FAIL", "semantic-invariants", subject, f"unsupported phase: {phase!r}")]

    if phase == "H1C9_MULTI_WITNESS_FINALITY_SCOUT":
        offsets = data["witness_offsets_seconds"]
        aggregate_offsets = sorted(int(k) for k in data["aggregate"].keys())
        if any(offset not in offsets for offset in aggregate_offsets):
            failures.append("aggregate contains witness offset not declared in witness_offsets_seconds")
        candidates = candidate_offsets_h1c9(data)
        if not candidates:
            failures.append("no public witness satisfies the frozen finality candidate rule")
        elif data["earliest_candidate_offset_seconds"] != candidates[0]:
            failures.append(
                f"earliest_candidate_offset_seconds={data['earliest_candidate_offset_seconds']} but recomputed={candidates[0]}"
            )
        if data["earliest_candidate_offset_seconds"] not in offsets:
            failures.append("earliest candidate is absent from witness_offsets_seconds")

    elif phase == "H1C11_TPLUS600_FRESH_FORWARD_RECORDER":
        hours = data["realtime_hours"]
        if data["realtime_decision_parity_pass"] != hours:
            failures.append("decision parity pass count does not equal realtime_hours")
        if data["row_t_ohlc_stable_after_witness_pass"] != hours:
            failures.append("OHLC stability pass count does not equal realtime_hours")
        if data["future_input_violations"] != 0:
            failures.append("future_input_violations must be zero")
        if data["live_finality_validation"] != "PASS":
            failures.append("live_finality_validation must be PASS")
        for label in ("decision_delay_from_hour_seconds", "witness_availability_lag_seconds"):
            summary = data[label]
            if not (summary["min"] <= summary["median"] <= summary["max"]):
                failures.append(f"{label} is not ordered min <= median <= max")
        ratio = parse_ratio(data["historical_preflight"])
        if ratio is None or ratio[0] != ratio[1]:
            failures.append("historical_preflight is not a full pass ratio")

    # Public evidence must never imply live authorization in these phases.
    for flag in ("live_execution_ready", "transaction_authorization", "counted_cycle"):
        if data.get(flag) is not False:
            failures.append(f"{flag} must remain false in public pre-execution evidence")

    if failures:
        return [CheckResult("FAIL", "semantic-invariants", subject, " | ".join(failures))]
    return [CheckResult("PASS", "semantic-invariants", subject, phase)]


def parse_sha_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = SHA_LINE_RE.match(line)
            if not match:
                raise ValueError(f"invalid SHA256SUMS line {line_number}: {raw.rstrip()}")
            digest, rel = match.groups()
            rel = rel.removeprefix("./")
            entries[rel] = digest.lower()
    return entries


def validate_hashes(repo_root: Path, evidence_files: list[Path], all_hashes: bool) -> list[CheckResult]:
    manifest = repo_root / "evidence" / "SHA256SUMS.txt"
    try:
        entries = parse_sha_manifest(manifest)
    except ValueError as exc:
        return [CheckResult("FAIL", "sha256", str(manifest.relative_to(repo_root)), str(exc))]

    if not entries:
        return [CheckResult("FAIL", "sha256", "evidence/SHA256SUMS.txt", "manifest missing or empty")]

    if all_hashes:
        targets = sorted(entries)
    else:
        targets = sorted(str(path.relative_to(repo_root)).replace("\\", "/") for path in evidence_files)

    results: list[CheckResult] = []
    for rel in targets:
        expected = entries.get(rel)
        if expected is None:
            results.append(CheckResult("FAIL", "sha256", rel, "file is not listed in evidence/SHA256SUMS.txt"))
            continue
        path = repo_root / rel
        if not path.is_file():
            results.append(CheckResult("FAIL", "sha256", rel, "listed file is missing"))
            continue
        actual = sha256_file(path)
        if actual != expected:
            results.append(CheckResult("FAIL", "sha256", rel, f"expected={expected} actual={actual}"))
        else:
            results.append(CheckResult("PASS", "sha256", rel, actual))
    return results


def run(repo_root: Path, all_hashes: bool = False, strict: bool = False) -> list[CheckResult]:
    repo_root = repo_root.resolve()
    schema_path = repo_root / "schemas" / "causal_evidence.schema.json"
    if not schema_path.is_file():
        return [CheckResult("FAIL", "setup", str(schema_path), "schema file not found")]

    try:
        schema = load_json(schema_path)
    except Exception as exc:
        return [CheckResult("FAIL", "setup", str(schema_path), f"cannot load schema: {exc}")]

    evidence_dir = repo_root / "evidence"
    evidence_files = sorted(evidence_dir.glob("*.json"))
    if not evidence_files:
        return [CheckResult("FAIL", "setup", "evidence/", "no public JSON evidence found")]

    results: list[CheckResult] = []
    supported_count = 0
    for path in evidence_files:
        subject = str(path.relative_to(repo_root)).replace("\\", "/")
        try:
            data = load_json(path)
        except Exception as exc:
            results.append(CheckResult("FAIL", "json-parse", subject, str(exc)))
            continue
        if not isinstance(data, dict):
            results.append(CheckResult("FAIL", "json-parse", subject, "top-level JSON must be an object"))
            continue
        results.extend(validate_secret_field_names(data, subject))
        phase = data.get("phase")
        if phase in SUPPORTED_PHASES:
            supported_count += 1
            results.extend(validate_schema(data, schema, subject))
            results.extend(validate_semantics(data, subject))
        elif strict:
            results.append(CheckResult("FAIL", "supported-phase", subject, f"unknown public phase: {phase!r}"))
        else:
            results.append(CheckResult("SKIP", "supported-phase", subject, f"unknown phase: {phase!r}"))

    if supported_count == 0:
        results.append(CheckResult("FAIL", "setup", "evidence/", "no supported evidence phase found"))

    results.extend(validate_hashes(repo_root, evidence_files, all_hashes=all_hashes))
    return results


def print_human(results: list[CheckResult]) -> None:
    print(f"Meteora Alpha Factory Evidence Validator v{VERSION}")
    for result in results:
        suffix = f" — {result.detail}" if result.detail else ""
        print(f"[{result.status}] {result.check}: {result.subject}{suffix}")
    passed = sum(r.status == "PASS" for r in results)
    skipped = sum(r.status == "SKIP" for r in results)
    failed = sum(r.status == "FAIL" for r in results)
    print(f"SUMMARY: {'PASS' if failed == 0 else 'FAIL'} (pass={passed}, skip={skipped}, fail={failed})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate sanitized Meteora Alpha Factory public evidence.")
    parser.add_argument("--repo-root", default=".", help="repository root (default: current directory)")
    parser.add_argument("--all-hashes", action="store_true", help="verify every path listed in evidence/SHA256SUMS.txt")
    parser.add_argument("--strict", action="store_true", help="fail on unsupported JSON evidence phases")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit machine-readable JSON")
    args = parser.parse_args()

    results = run(Path(args.repo_root), all_hashes=args.all_hashes, strict=args.strict)
    failed = any(r.status == "FAIL" for r in results)
    if args.json_output:
        payload = {
            "validator": "meteora-alpha-factory-evidence",
            "version": VERSION,
            "status": "FAIL" if failed else "PASS",
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_human(results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
