"""frameworks/wtpc/lib/_tagdefs - tag-category definition + URN resolution on the vCenter native plane.

WHY NATIVE. VCF Operations centralized Tag Management is the north-star create plane: one API defines
a category once and Operations mirrors it to every managed vCenter. But the Ops-to-vCenter projection
of a NEWLY created category is unreliable on current builds (a fresh category is not mirrored into the
vCenter tagging service for an unbounded time, so it cannot be attached). Until that is fixed, the
estate DEFINES categories natively on the vCenter (instant, projection-proof). Consumers reference
categories BY NAME and never see the plane, so a future switch back to the centralized API changes
this module, not the estate.

Every method takes a ``vc`` session (lib/_client.VcSession). Idempotent; dry-run aware; only ever
mutates categories it created - identified by the ``DEF_MARKER`` stamped in the description - so a
pre-existing operator category of the same name is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

from lib._client import HttpError

_CIS = "/cis/tagging"
DEF_MARKER = "[pca-wtpc]"  # stamped in a native category's description -> safe, self-only teardown


def _val(resp):
    """Unwrap a vSphere Automation response (``{"value": ...}`` on some builds, bare on others)."""
    b = resp.json()
    return b.get("value", b) if isinstance(b, dict) else b


@dataclass
class CategoryReport:
    """The outcome of ensuring one category on one vCenter - the unit the CLI renders."""

    vcenter: str
    name: str
    object_type: str
    category_action: str = ""  # exists | create | would-create | conflict | delete | would-delete | absent
    category_id: str | None = None
    values_created: list[str] = field(default_factory=list)
    values_existing: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.category_action != "conflict"


@dataclass
class TagCatalog:
    """Per-vCenter name<->URN maps, read from the vCenter tagging service (source of truth)."""

    urn_by_cv: dict[tuple[str, str], str]
    cv_by_uuid: dict[str, tuple[str, str]]

    def urn(self, category: str, value: str) -> str | None:
        return self.urn_by_cv.get((category, value))

    def uuid(self, category: str, value: str) -> str | None:
        """The bare tag uuid (URN segment 3) - the form the tag-association plane re-wraps to attach."""
        urn = self.urn_by_cv.get((category, value))
        parts = urn.split(":") if urn else []
        return parts[3] if len(parts) >= 5 else None


class NativeVcenterTagProvider:
    """Defines tag categories natively on a vCenter and reads its tag catalog."""

    # -- reads ------------------------------------------------------------------------------------
    def cat_index(self, vc) -> dict[str, dict]:
        """{category name -> {id, description}} for every tagging category on the vCenter. Read ONCE
        per vCenter and threaded into ensure/teardown - re-reading per category is the slow path."""
        out: dict[str, dict] = {}
        for cid in _val(vc.get(f"{_CIS}/category")) or []:
            try:
                d = _val(vc.get(f"{_CIS}/category/{quote(cid, safe='')}"))
            except HttpError:
                continue
            out[d.get("name")] = {"id": cid, "description": d.get("description") or ""}
        return out

    def _tags_of(self, vc, cat_id: str) -> dict[str, str]:
        """{value name -> tag URN} for one category."""
        try:
            ids = _val(vc.post(f"{_CIS}/tag", params={"action": "list-tags-for-category"},
                               json={"category_id": cat_id}))
        except HttpError:
            ids = []
        out: dict[str, str] = {}
        for tid in ids or []:
            try:
                out[_val(vc.get(f"{_CIS}/tag/{quote(tid, safe='')}")).get("name")] = tid
            except HttpError:
                continue
        return out

    # -- definition (idempotent) ------------------------------------------------------------------
    def ensure_category(self, vc, vc_name: str, name: str, object_type: str, cardinality: str,
                        values: list[str], index: dict[str, dict], *, dry_run: bool) -> CategoryReport:
        """Ensure a native category ``name`` (scoped to ``object_type``) and its ``values`` exist.
        Reuses an existing OURS category; refuses to adopt a same-named category we did not create."""
        rep = CategoryReport(vcenter=vc_name, name=name, object_type=object_type)
        cat = index.get(name)
        if cat and DEF_MARKER not in cat["description"]:
            rep.category_action = "conflict"
            rep.note = f"pre-existing category {name!r} is not ours (no {DEF_MARKER}) - left untouched"
            return rep
        if not cat:
            if dry_run:
                rep.category_action = "would-create"
                rep.values_created = list(values)
                return rep
            rep.category_id = _val(vc.post(f"{_CIS}/category", json={
                "name": name, "description": f"{DEF_MARKER} WTPC taxonomy ({object_type})",
                "cardinality": cardinality, "associable_types": [object_type]}))
            rep.category_action = "create"
            have: dict[str, str] = {}
        else:
            rep.category_action = "exists"
            rep.category_id = cat["id"]
            have = self._tags_of(vc, cat["id"])
        for v in values:
            if v in have:
                rep.values_existing.append(v)
            elif dry_run:
                rep.values_created.append(v)
            else:
                vc.post(f"{_CIS}/tag", json={"name": v, "description": DEF_MARKER,
                                             "category_id": rep.category_id})
                rep.values_created.append(v)
        return rep

    def ensure_value(self, vc, category_id: str, value: str) -> str | None:
        """Idempotently ensure a single value exists under an existing category; return its tag URN."""
        have = self._tags_of(vc, category_id)
        if value in have:
            return have[value]
        vc.post(f"{_CIS}/tag", json={"name": value, "description": DEF_MARKER, "category_id": category_id})
        return self._tags_of(vc, category_id).get(value)

    def teardown_category(self, vc, vc_name: str, name: str, index: dict[str, dict],
                          *, dry_run: bool) -> CategoryReport:
        """Delete a native category we created (its values first). A value with live assignments
        returns 403 - detach it on the tag-association plane before teardown."""
        rep = CategoryReport(vcenter=vc_name, name=name, object_type="")
        cat = index.get(name)
        if not cat:
            rep.category_action = "absent"
            return rep
        if DEF_MARKER not in cat["description"]:
            rep.category_action = "conflict"
            rep.note = f"category {name!r} is not ours - refusing to delete"
            return rep
        if dry_run:
            rep.category_action = "would-delete"
            rep.values_existing = list(self._tags_of(vc, cat["id"]))
            return rep
        for _v, urn in self._tags_of(vc, cat["id"]).items():
            try:
                vc.delete(f"{_CIS}/tag/{quote(urn, safe='')}")
            except HttpError as e:
                rep.note = f"value delete {e.status_code} (detach assignments first?)"
        vc.delete(f"{_CIS}/category/{quote(cat['id'], safe='')}")
        rep.category_action = "delete"
        return rep

    # -- resolution (for the tag-association plane) -----------------------------------------------
    def catalog(self, vc, *, index: dict[str, dict] | None = None,
                only: set[str] | None = None) -> TagCatalog:
        """Read the vCenter's tags into (category,value)->URN and uuid->(category,value) maps.
        ``only`` restricts resolution to these category names - a consumer that owns a handful of
        categories should pass its own, since every tag is a per-tag GET on a slow tagging API."""
        cats = index if index is not None else self.cat_index(vc)
        urn_by_cv: dict[tuple[str, str], str] = {}
        cv_by_uuid: dict[str, tuple[str, str]] = {}
        for cname, cat in cats.items():
            if only is not None and cname not in only:
                continue
            for vname, urn in self._tags_of(vc, cat["id"]).items():
                urn_by_cv[(cname, vname)] = urn
                parts = urn.split(":")  # urn:vmomi:InventoryServiceTag:<uuid>:GLOBAL
                if len(parts) >= 5:
                    cv_by_uuid[parts[3]] = (cname, vname)
        return TagCatalog(urn_by_cv, cv_by_uuid)


__all__ = ["DEF_MARKER", "CategoryReport", "NativeVcenterTagProvider", "TagCatalog", "_val"]
