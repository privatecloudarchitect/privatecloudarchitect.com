# References

Where each part of this solution is taught in more depth, and the runnable proof
behind the claims. Every link below was verified reachable when this folder was
assembled.

## Published, public sources

The teaching and the proof are public on privatecloudarchitect.com and its companion
repository. These carry no estate-specific details and are safe to share with anyone.

- **The solution, as one page** (this folder, published and browsable):
  https://privatecloudarchitect.com/solutions/tenant-self-service-with-isolation
- **Field note 03, the programmatic vend** (the public version of module 04):
  https://privatecloudarchitect.com/notes/vcfa-project-vending
- **Access control, the handbook chapter** (the two-plane model of module 01, in
  depth: four layers, four dials, two surfaces):
  https://privatecloudarchitect.com/handbook/access-control
- **Field note 01, access control as three factors** (the deployment-plane isolation
  proof and the group pattern of module 05):
  https://privatecloudarchitect.com/notes/vcfa-access-control-three-factors
- **The isolation design, assembled** (the capstone chapter, with the build recipe):
  https://privatecloudarchitect.com/handbook/isolation-design
- **The capacity plane** (where the namespace spec's budget comes from, and the
  fresh-project namespace create corrected):
  https://privatecloudarchitect.com/handbook/capacity-plane

## The runnable proof harness

The full multi-user Day-2 isolation matrix, including the governance flip, is a
runnable companion that proves the design on your own estate, read-only or
round-tripped, and leaves it as it found it:

- **Companion harness, isolation-design** (manifests plus a verifier; the
  namespace manifest uses `generateName` and `kubectl create`, matching module 04):
  https://github.com/privatecloudarchitect/privatecloudarchitect.com/tree/main/handbook/isolation-design

## The reference artifact

A single-page, printable admin reference covering the model, the tier ladder, the
isolation ceiling, and the vend runbook. It ships in this folder, self-contained
(open it in any browser or print to PDF):

- [`admin-reference.html`](admin-reference.html)
