"""frameworks/cartography/lib - the estate's shared mechanics.

  _client   - the environment-driven VCF Automation + vCenter sessions
  _classify - the pure classification core (labels in, classifications + proposals out)
  _models   - the reconcile primitive (desired vs current -> idempotent actions)
  _taxonomy - the concept -> live category-name resolver over taxonomy.yaml
  _tagdefs  - tag-category definition + URN resolution on the vCenter native plane
  _tagging  - the vCenter tag-association plane: the universal-tag URN + attach/detach/list

Import convention (works because the estate dir is sys.path[0] when a script is run directly):
    from lib._client import vcfa_client
    from lib._classify import classify_function
"""
