"""frameworks/wtpc/lib - the estate's shared cross-cutting mechanics (the DRY seam).

The estate's scripts are generators, reconcilers, and evidence CLIs - each a standalone entry point
run as `python <script>.py` from the estate dir. That standalone-per-script model is deliberate
(portable, copy-a-script-and-go), but it had one cost: the same VCF-Ops mechanics would be
hand-copied into every script. This package is the single home for those mechanics, so a reader
learns each one ONCE and every script tells its own story (what it generates) instead of re-telling
how to reach Operations.

  _client   - the environment-driven Operations + vCenter sessions (ops_client / vcenter_client)
              and the policy_index read
  _sm       - super-metric mechanics: the stat-key form, adopt-by-name upsert, policy activation
  _groups   - custom-group reads (the /api/resources/groups index) + the tag-rule membership payload
  _tagging  - the vCenter tag-association plane: the universal-tag URN + attach/detach/list
  _tagdefs  - tag-category definition + URN resolution on the vCenter native plane
  _taxonomy - the concept -> live category-name resolver over taxonomy.yaml
  _alerts   - the paginated adopt-by-name lookup for symptom/alert definitions
  _evidence - the shared latest-stat read for the read-only estate rollups
  _postures - posture discovery + the content-identity seam (postures/<P>.yaml)

Import convention (works because the estate dir is sys.path[0] when a script is run directly):
    from lib._client import ops_client
    from lib._sm import sm_stat_key, upsert_supermetric
"""
