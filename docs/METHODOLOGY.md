# Methodology

## Core question

Does an actively managed Meteora DLMM strategy create value versus a fixed 50/50 SOL-USDC benchmark after causality, accounting, execution, hedging and scale are treated explicitly?

## Causal decision protocol

- Hour anchor: `t`.
- Frozen witness: exact row at `t + 600 seconds` must be present in an accepted stable local snapshot.
- Decision inputs: timestamps `<= t` only.
- Decision wall clock: actual witness-acceptance time; never backdated.
- Missing witness: fail closed.
- Future-input use: forbidden.
- Finality test: exact OHLC stability against later canonical reconciliation.

## Validation history

The earlier +300 second witness was not retained. A fresh-forward test observed a material post-witness revision. A later multi-witness study evaluated +300 through +3300 seconds. +600 seconds was the earliest tested offset with 12/12 exact OHLC stability, 12/12 decision parity and zero future-input violations. The candidate was frozen and then validated on 12 new hours.

## Evidence labels

- **Exact evidence:** directly reconciled under a frozen protocol.
- **Reconstructed evidence:** derived from historical state reconstruction with documented assumptions.
- **Proxy evidence:** approximate economic representation.
- **Descriptive shadow output:** forward observation that is not a forecast or realized execution claim.
