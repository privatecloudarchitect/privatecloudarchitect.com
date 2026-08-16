#!/usr/bin/env python3
"""
Package the per-posture WTPC ViewDefs into one-click `Views > Manage > Import` bundles.

Each bundle is a zip holding a single `content.xml` of the form
    <?xml ...?><Content><Views><ViewDef/>...</Views></Content>
- exactly the format VCF Ops `Views > Manage > Import` accepts, and the same
format the original single-slot `wtpc-views.import.zip` used.

The bundle is assembled by *byte-preserving string surgery* on the committed raw
`content/*.view.xml` files (each already a complete
`<Content><Views><ViewDef></Views></Content>` document emitted by build_views.py /
build_governance_views.py): the verbatim `<ViewDef>` substrings are concatenated
under one `<Views>`. This is proven byte-identical to the original hand-made,
live-imported prod-db bundle (the regression guard in main() asserts it while the
legacy zip is still present).

No network / no live calls - a pure file emitter. Deterministic (fixed zip timestamp),
so re-runs produce identical bytes.

Run:  python build_view_bundles.py [--check]
  (no args)  (re)write the per-posture bundles under content/
  --check    build in memory + run the self-tests, write nothing (CI/prepush gate)
"""
import glob
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "content")

PREFIX = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Content><Views>'
SUFFIX = "</Views></Content>"
ZIP_TS = (1980, 1, 1, 0, 0, 0)  # fixed -> reproducible zip bytes (matches build_governance_dashboard.py)

from lib._postures import content_ids, discover   # elevator seam: the estate posture set + per-posture ids

# posture / group  ->  (raw .view.xml glob, output bundle name, expected ViewDef count). The per-posture
# entries are DERIVED: each posture's .view.xml glob comes from its content_ids.view_prefix, so a new
# posture joins the bundle set with no edit here. governance is the one fixed cross-posture bundle.
BUNDLES = {p: (f"wtpc-{content_ids(p)['view_prefix']}-*.view.xml", f"wtpc-views-{p}.import.zip", 5)
           for p in discover()}
if glob.glob(os.path.join(CONTENT, "wtpc-gov-*.view.xml")):   # the cross-posture governance bundle (a later slice)
    BUNDLES["governance"] = ("wtpc-gov-*.view.xml", "wtpc-views-governance.import.zip", 4)

LEGACY = "wtpc-views.import.zip"  # the single-slot prod-db bundle this tool supersedes


def _viewdef_body(path):
    """Extract the verbatim <ViewDef>...</ViewDef> substring from a raw view file (byte-preserving)."""
    txt = open(path, encoding="utf-8").read()
    if not txt.startswith(PREFIX) or not txt.rstrip().endswith(SUFFIX):
        raise ValueError(f"{os.path.basename(path)}: not a <Content><Views><ViewDef> document")
    inner = txt.split("<Views>", 1)[1].rsplit("</Views>", 1)[0]
    if inner.count("<ViewDef ") != 1:
        raise ValueError(f"{os.path.basename(path)}: expected exactly 1 ViewDef, found {inner.count('<ViewDef ')}")
    return inner


def build_content_xml(files):
    """Concatenate the verbatim ViewDef bodies (sorted filename order) into one content.xml string."""
    return PREFIX + "".join(_viewdef_body(f) for f in files) + SUFFIX


def validate(content_xml, expect_count):
    """Structural self-test: parses, ViewDef count, unique non-empty ids, Title + Description each."""
    root = ET.fromstring(content_xml)  # our own generated, trusted content
    vds = root.findall("Views/ViewDef")
    assert len(vds) == expect_count, f"expected {expect_count} ViewDefs, got {len(vds)}"
    ids = [vd.get("id") for vd in vds]
    assert all(ids), "a ViewDef is missing its id"
    assert len(set(ids)) == len(ids), f"duplicate ViewDef ids: {ids}"
    for vd in vds:
        assert vd.findtext("Title"), f"ViewDef {vd.get('id')}: missing Title"
        assert vd.find("Description") is not None, f"ViewDef {vd.get('id')}: missing Description"
    return ids


def main():
    check = "--check" in sys.argv[1:]

    # Regression proof: while the legacy single-slot bundle still exists, the prod-db
    # bundle we emit must be byte-identical to it (the original hand-made, live-imported one).
    legacy_path = os.path.join(CONTENT, LEGACY)
    legacy_content = None
    if os.path.exists(legacy_path):
        with zipfile.ZipFile(legacy_path) as z:
            legacy_content = z.read("content.xml").decode("utf-8")

    results = []
    for posture, (pat, out, count) in BUNDLES.items():
        files = sorted(glob.glob(os.path.join(CONTENT, pat)))
        if len(files) != count:
            raise SystemExit(f"{posture}: found {len(files)} view files, expected {count} ({pat})")
        content_xml = build_content_xml(files)
        ids = validate(content_xml, count)
        if posture == "prod-latency-critical-db" and legacy_content is not None:
            assert content_xml == legacy_content, (
                "prod-db bundle diverged from the proven legacy wtpc-views.import.zip - "
                "the string-surgery recipe or a raw view file changed; investigate before shipping"
            )
        results.append((posture, out, files, ids, content_xml))

    if check:
        for posture, out, files, ids, _ in results:
            print(f"[check] {posture}: {len(files)} views -> {out}  ({len(ids)} ViewDefs) OK")
        tail = "; prod-db byte-identical to legacy" if legacy_content else ""
        print(f"[check] all {len(results)} bundles valid{tail}")
        return

    for posture, out, files, ids, content_xml in results:
        path = os.path.join(CONTENT, out)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo("content.xml", ZIP_TS), content_xml)
        names = ", ".join(os.path.basename(f) for f in files)
        print(f"  emitted {out}  ({len(files)} ViewDefs: {names})")

    print(f"\n{len(results)} bundles written to content/. Import each via Ops UI > Views > Manage > Import.")


if __name__ == "__main__":
    main()
