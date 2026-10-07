#!/usr/bin/env python3
"""export.py - bring the super metrics you already built in the console under the converge.

Reads every super metric whose name carries your owner prefix and separator, and writes them in the shape
desired-state.json uses: name, formula, description. Then

  python3 export.py > mine.json
  python3 converge.py --state mine.json --dry-run      # expect every object "unchanged"

A dry run that reports every exported object unchanged is the proof that the converge has adopted what you
built by hand, by name, without touching it. From then on the file is the source: edit it, converge it.

The formula and description are decoded from the HTML entities the list read returns them in (comparison
operators arrive as &gt; and &lt;), so the file carries what you typed in the formula editor.

Read-only: the broker's token exchange, a POST that changes nothing, and one list read. It writes only to
stdout.

Usage:  python3 export.py > mine.json
Env:    see opslib.py; OPS_OWNER is the owner prefix (default PCA), matched with its " - " separator
"""

import html
import json
import os
import sys

from opslib import bearer, ops


def main():
    owner = os.environ.get("OPS_OWNER", "PCA")
    st, body = ops("GET", "/api/supermetrics", bearer(), params={"pageSize": 2000})
    if st != 200:
        sys.exit(f"FATAL: list supermetrics -> HTTP {st}: {body}")
    mine = sorted((s for s in body.get("superMetrics", []) if s.get("name", "").startswith(owner + " - ")),
                  key=lambda s: s["name"])
    state = {"comment": f"Exported from the instance by export.py: every super metric named '{owner} - ...'. "
                        "Converge it with: python3 converge.py --state <this file>",
             "supermetrics": [{"name": s["name"],
                               "formula": html.unescape(s.get("formula") or ""),
                               "description": html.unescape(s.get("description") or "")} for s in mine]}
    json.dump(state, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    print(f"export.py: {len(mine)} super metric(s) named '{owner} - ...'", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
