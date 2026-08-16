"""wtpc/lib/_tagging — the vCenter tag-association plane.

Cluster TIER tags and per-VM POSTURE tags are both applied through vCenter's tag-association API, not Ops:
the Ops tag-assignment PATCH silently 202-no-ops when the identity lacks the vCenter attach privilege,
while vCenter fails LOUD (403). An Ops tag uuid doubles as vCenter's universal-tag URN. These
three primitives — URN, and list/attach/detach parameterised by object type — are what the two callers
share: the tier cluster tagger (reconcile_tiers) and the per-VM VcActuator (reconcile_posture_membership),
each of which keeps its own name→moref and uuid→(category,value) maps.
"""
from __future__ import annotations

from urllib.parse import quote

_ASSOC = "/cis/tagging/tag-association"


def tag_urn(uuid: str) -> str:
    """The vCenter universal-tag URN for an Ops tag uuid: urn:vmomi:InventoryServiceTag:<uuid>:GLOBAL."""
    return f"urn:vmomi:InventoryServiceTag:{uuid}:GLOBAL"


def list_attached_tags(vc, object_id: str, object_type: str) -> list[str]:
    """The tag URNs currently attached to a vCenter object — the source of truth (Ops' summary|tag property
    lags). `object_type` is the vCenter type, e.g. 'ClusterComputeResource' or 'VirtualMachine'."""
    body = vc.post(_ASSOC, params={"action": "list-attached-tags"},
                   json={"object_id": {"id": object_id, "type": object_type}}).json()
    return body.get("value", body) if isinstance(body, dict) else (body or [])


def attach_tag(vc, object_id: str, object_type: str, uuid: str) -> None:
    """Attach tag `uuid` to a vCenter object (fails LOUD/403 if the identity is unprivileged)."""
    vc.post(f"{_ASSOC}/{quote(tag_urn(uuid), safe='')}", params={"action": "attach"},
            json={"object_id": {"id": object_id, "type": object_type}})


def detach_tag(vc, object_id: str, object_type: str, uuid: str) -> None:
    """Detach tag `uuid` from a vCenter object."""
    vc.post(f"{_ASSOC}/{quote(tag_urn(uuid), safe='')}", params={"action": "detach"},
            json={"object_id": {"id": object_id, "type": object_type}})
