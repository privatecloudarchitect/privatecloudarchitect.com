# privatecloudarchitect.com companion artifacts

Runnable reference artifacts behind the sheets at [privatecloudarchitect.com](https://privatecloudarchitect.com).
Every directory here backs one published sheet: the sheet teaches the model and carries the
evidence tiers; the artifact in this repo is the thing you run on your own estate.

## The contract

Everything in this repo satisfies four rules before it is pushed:

1. **It backs a published sheet.** The map below names the sheet each directory belongs to.
2. **It was proven on a live VMware Cloud Foundation estate**, and each directory's README states
   the build and the date it was proven on.
3. **It is parameterized for your estate.** Environment variables and marked placeholders carry
   everything estate-specific; nothing here assumes the estate it was proven on.
4. **What ships is what ran.** The exact files here were re-run against a live estate before
   publication, not sanitized afterward and assumed equivalent.

## The map

| Directory | Backs | What it is |
|---|---|---|
| [`handbook/isolation-design/`](handbook/isolation-design/) | [The isolation design, assembled](https://privatecloudarchitect.com/handbook/isolation-design) and [field note 01](https://privatecloudarchitect.com/notes/vcfa-access-control-three-factors) | Declarative manifests plus a verifier that proves per-user isolation on your build |
| [`handbook/day2-governance/`](handbook/day2-governance/) | [Day-2 governance](https://privatecloudarchitect.com/handbook/day2-governance) | The two-policy HARD change as importable JSON, named per the sheet's convention |
| [`handbook/memory-tiering/`](handbook/memory-tiering/) | [Memory tiering candidacy](https://privatecloudarchitect.com/handbook/memory-tiering) | The lens end to end: the metrics (formulas plus id-preserving package), the three views, and the readiness dashboard |
| [`handbook/wtpc/`](handbook/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) | The starter catalog's three posture records, machine-readable and instance-independent |

## How to read this repo against the site

The site marks every claim with an evidence tier (`live` / `repo` / `doc`, defined on the
[method page](https://privatecloudarchitect.com/method)). This repo is the visible referent of the
`repo` tier: when a sheet links an artifact here, that artifact is the proof harness or content
the claim rests on. New artifacts appear only when a sheet references them, and corrections are
dated in the artifact's README, never silent.

License: [MIT](LICENSE).
