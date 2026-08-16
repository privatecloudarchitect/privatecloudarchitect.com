"""wtpc/lib/_groups — custom-group reads + the tag-rule membership payload.

Everything that touches /api/resources/groups: the endpoint (its literal was redefined in four scripts),
the index read (whose three includePolicy flavours the callers had each spelled out inline), the two derived
name→id / name-set views, and the Container/Environment tag-rule payload a posture's and a tier's groups are
born with (it used to live in an entry script, instantiate_posture, and be imported script-to-script).
"""
from __future__ import annotations

GROUPS_ENDPOINT = "/api/resources/groups"


def list_groups(c, include_policy=None) -> list[dict]:
    """Every custom group. `include_policy=None` omits the flag (the light read most callers use);
    True → includePolicy=true (carry each group's bound policy — the policy/priority reconcilers need it);
    False → includePolicy=false (the explicit light read the scorecards use). Always `_no_links`."""
    params = {"_no_links": "true"}
    if include_policy is not None:
        params["includePolicy"] = "true" if include_policy else "false"
    return c.get(GROUPS_ENDPOINT, params=params).json().get("groups", [])


def group_ids(c) -> dict[str, str]:
    """{group name: id} for every custom group."""
    return {g.get("resourceKey", {}).get("name"): g["id"] for g in list_groups(c)}


def group_names(c) -> set:
    """The set of live custom-group names."""
    return {g.get("resourceKey", {}).get("name") for g in list_groups(c)}


def group_members(c, group_id: str) -> list[dict]:
    """The live members (resourceList) of a custom group by id — the read the evidence rollups do per group."""
    return c.get(f"{GROUPS_ENDPOINT}/{group_id}/members", params={"_no_links": "true"}).json().get("resourceList", [])


def make_tag_rule_group(name: str, resource_kind: str, tag_conditions: list[tuple[str, str]]) -> dict:
    """A custom group (Container/Environment) whose membership is an AND of resourceTagConditionRules — the
    shape a posture's VMs group and its Host/Cluster seeds are born with (instantiate_posture), and the
    tier=<name> cluster groups (reconcile_tiers). The Host/Cluster seeds are later converted to derived
    `includedResources` by reconcile_infra_groups (the follows-the-workload model)."""
    return {
        "resourceKey": {"name": name, "adapterKindKey": "Container", "resourceKindKey": "Environment",
                        "resourceIdentifiers": []},
        "autoResolveMembership": True,
        "membershipDefinition": {
            "includedResources": [], "excludedResources": [], "custom-group-properties": [],
            "rules": [{"resourceKindKey": {"resourceKind": resource_kind, "adapterKind": "VMWARE"},
                       "statConditionRules": [], "propertyConditionRules": [], "resourceNameConditionRules": [],
                       "relationshipConditionRules": [],
                       "resourceTagConditionRules": [{"category": cat, "compareOperator": "EQ", "stringValue": val}
                                                     for cat, val in tag_conditions]}]}}
