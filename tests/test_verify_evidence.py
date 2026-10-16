import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.verify_evidence import (
    load_json,
    run,
    validate_secret_field_names,
    validate_semantics,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class PublicEvidenceValidatorTests(unittest.TestCase):
    def test_repository_public_evidence_passes(self):
        results = run(REPO_ROOT, all_hashes=False, strict=True)
        failures = [result for result in results if result.status == "FAIL"]
        self.assertEqual([], failures, "\n".join(f"{r.check}: {r.subject}: {r.detail}" for r in failures))

    def test_h1c11_detects_parity_tamper(self):
        path = REPO_ROOT / "evidence" / "H1C11_TPLUS600_VALIDATION_SUMMARY.json"
        data = load_json(path)
        tampered = copy.deepcopy(data)
        tampered["realtime_decision_parity_pass"] = tampered["realtime_hours"] - 1
        results = validate_semantics(tampered, "tampered-h1c11")
        self.assertTrue(any(result.status == "FAIL" for result in results))

    def test_h1c9_recomputes_earliest_candidate(self):
        path = REPO_ROOT / "evidence" / "H1C9_MULTI_WITNESS_SUMMARY.json"
        data = load_json(path)
        tampered = copy.deepcopy(data)
        tampered["earliest_candidate_offset_seconds"] = 300
        results = validate_semantics(tampered, "tampered-h1c9")
        self.assertTrue(any(result.status == "FAIL" for result in results))

    def test_secret_like_public_field_is_rejected(self):
        data = {"phase": "example", "api_key": "not-a-real-key"}
        results = validate_secret_field_names(data, "secret-surface")
        self.assertTrue(any(result.status == "FAIL" for result in results))

    def test_evidence_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "evidence").mkdir()
            (root / "schemas").mkdir()
            # Use the real schema and both supported evidence fixtures.
            (root / "schemas" / "causal_evidence.schema.json").write_bytes(
                (REPO_ROOT / "schemas" / "causal_evidence.schema.json").read_bytes()
            )
            fixtures = [
                "H1C9_MULTI_WITNESS_SUMMARY.json",
                "H1C11_TPLUS600_VALIDATION_SUMMARY.json",
            ]
            manifest_lines = []
            for name in fixtures:
                source = REPO_ROOT / "evidence" / name
                target = root / "evidence" / name
                target.write_bytes(source.read_bytes())
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                manifest_lines.append(f"{digest}  ./evidence/{name}\n")
            (root / "evidence" / "SHA256SUMS.txt").write_text("".join(manifest_lines), encoding="utf-8")
            # Tamper after manifest creation.
            target = root / "evidence" / "H1C11_TPLUS600_VALIDATION_SUMMARY.json"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            results = run(root, all_hashes=False, strict=True)
            self.assertTrue(any(r.status == "FAIL" and r.check == "sha256" for r in results))


if __name__ == "__main__":
    unittest.main()
