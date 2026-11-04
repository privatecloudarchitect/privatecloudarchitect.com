"""The companion's own layout: one HTML frame with inline tokens, both themes, no site file and no external resource."""

from __future__ import annotations

import html

E = html.escape
LAYOUT = "strategy-companion layout 1"

CSS = """
:root{--bg:#f7f6f2;--ink:#1f2420;--ink-2:#4a524c;--rule:#d9d6cc;--accent:#2f5d50;--warn:#8a5a14;--bad:#8c2f2f;--ok:#2f6b3a;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15181a;--ink:#e6e4dd;--ink-2:#aeb3ab;--rule:#3a3f3b;--accent:#8fc1b2;--warn:#d9a441;--bad:#d97b7b;--ok:#86c791}}
:root[data-theme="dark"]{--bg:#15181a;--ink:#e6e4dd;--ink-2:#aeb3ab;--rule:#3a3f3b;--accent:#8fc1b2;--warn:#d9a441;--bad:#d97b7b;--ok:#86c791}
html,body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}
main{max-width:72rem;margin:0 auto;padding:1.5rem 1rem}
h1{font-size:1.6rem;margin:0 0 .25rem}h2{font-size:1.15rem;margin:1.5rem 0 .5rem;color:var(--accent)}
p.dek{color:var(--ink-2);margin:0 0 1rem}
table{border-collapse:collapse;width:100%;font-size:.95rem}th,td{text-align:left;vertical-align:top;padding:.35rem .5rem;border-top:1px solid var(--rule)}
th{font-weight:600;color:var(--ink-2);font-size:.8rem;letter-spacing:.04em;text-transform:uppercase}
.wrap{overflow-x:auto}code{font-family:var(--mono);font-size:.9em}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.ill{font-style:italic;color:var(--ink-2)}
p.prov{margin-top:2rem;padding-top:.75rem;border-top:1px solid var(--rule);font-size:.8rem;color:var(--ink-2)}
nav a{margin-right:1rem}
"""


def page(
    title: str,
    dek: str,
    body: str,
    provenance: str,
    source: str,
    nav: list[tuple[str, str]] | None = None,
) -> str:
    links = "".join(f'<a href="{E(h)}">{E(t)}</a>' for t, h in nav or [])
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{E(title)}</title><style>{CSS}</style></head>"
        f'<body><main data-source="{E(source)}" data-layout="{E(LAYOUT)}">'
        f'<nav>{links}</nav><h1>{E(title)}</h1><p class="dek">{E(dek)}</p>{body}'
        f'<p class="prov">{E(provenance)}</p></main></body></html>\n'
    )


def table(head: list[str], rows: list[list[str]]) -> str:
    """Rows of already-escaped cells."""
    th = "".join(f"<th>{E(h)}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def kind(k: str | None) -> str:
    return f'<span class="ill">{E(k)}</span>' if k == "illustrative" else E(k or "")
