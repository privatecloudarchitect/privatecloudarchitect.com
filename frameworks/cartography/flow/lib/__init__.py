"""The flow lens's internals: a standalone vRNI client and the two pure analysis cores.

`_client` is the only network boundary; `_collect` is the read shell over it; `_shared_services`
(Phase 4) and `_boundaries` (Phase 5) are deterministic, I/O-free, and unit-testable with synthetic
flows, which is what the offline `--self-test` exercises."""
