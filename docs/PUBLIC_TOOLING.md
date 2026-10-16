# Public tooling v0.1

This release adds a small, auditable validation surface for the sanitized evidence in this repository. It is deliberately separated from proprietary strategy logic.

## What is public

- a JSON Schema for the sanitized H1C9/H1C11 causal-finality summaries;
- a local, read-only evidence validator;
- cross-field semantic checks that recompute public pass/fail relationships;
- SHA-256 verification for evidence files;
- a public-surface check that rejects secret-like JSON field names;
- unit tests and GitHub Actions CI.

## What is not public

The tooling contains no alpha thresholds, pool-selection rules, custody material, API credentials, private keys, signing logic, live transaction instructions or parameters intended to reproduce the proprietary strategy.

## Run locally

```bash
python -m pip install -r requirements-dev.txt
python tools/verify_evidence.py --repo-root . --strict
python -m unittest discover -s tests -v
```

To verify every path currently listed in the SHA-256 manifest rather than only JSON evidence files:

```bash
python tools/verify_evidence.py --repo-root . --strict --all-hashes
```

## Expected result

The current sanitized evidence should end with a `SUMMARY: PASS` line. A non-zero process exit code means that at least one enabled check failed.

## Security / execution boundary

The validator performs no network requests, reads no wallets and signs no transactions. It operates only on repository files.
