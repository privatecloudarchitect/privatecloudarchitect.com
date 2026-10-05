"""The record contract for the log and flow harnesses (CHAPTER-DOCTRINE section 5).

A harness registers every estate value it reads (names, FQDNs, addresses, identifiers) under a category, and
the record it writes carries a stable placeholder in each one's place, `{{proxy-1}}`, `{{vcenter-2}}`. The
replacement is a single pass that tries the longest value first at every position, so a name that contains
another name is replaced whole. It runs on the record's values before serialization, so a value JSON would escape
(a quote, a backslash) is still found. A record in which any registered value survives, in any letter case, is not
written: a value that reached the record in a form the scrub did not match stops the write instead of leaking.

Standard library only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class Scrubber:
    def __init__(self) -> None:
        self._placeholder: dict[str, str] = {}
        self._count: dict[str, int] = {}

    def add(self, value: Any, category: str) -> str:
        """Register one estate value; returns its placeholder. Empty values are ignored."""
        text = str(value or "").strip()
        if not text:
            return text
        if text not in self._placeholder:
            self._count[category] = self._count.get(category, 0) + 1
            self._placeholder[text] = "{{" + f"{category}-{self._count[category]}" + "}}"
        return self._placeholder[text]

    def add_host(self, fqdn: Any, category: str) -> str:
        """An FQDN, its short name and its domain, so a bare host or domain cannot slip through."""
        text = str(fqdn or "").strip()
        if not text:
            return text
        placeholder = self.add(text, category)
        if "." in text and not re.fullmatch(r"[\d.]+", text):
            short, domain = text.split(".", 1)
            self.add(short, category + "-name")
            self.add(domain, "domain")
        return placeholder

    def scrub(self, text: str) -> str:
        if not self._placeholder:
            return text
        values = sorted(self._placeholder, key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(v) for v in values))
        return pattern.sub(lambda m: self._placeholder[m.group(0)], text)

    def scrub_obj(self, obj: Any) -> Any:
        """The same replacement over a record's keys and string values, before it is serialized."""
        if isinstance(obj, dict):
            return {self.scrub(str(k)): self.scrub_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.scrub_obj(v) for v in obj]
        return self.scrub(obj) if isinstance(obj, str) else obj

    def survivors(self, text: str) -> list[str]:
        """Categories of registered values still present in any letter case, raw or JSON-escaped; values
        themselves are never returned."""
        low = text.lower()
        left = set()
        for value, placeholder in self._placeholder.items():
            forms = {value.lower(), json.dumps(value)[1:-1].lower()}
            if any(form in low for form in forms):
                left.add(placeholder.strip("{}"))
        return sorted(left)

    def write(self, path: Path, record: dict[str, Any]) -> str:
        text = json.dumps(self.scrub_obj(record), indent=1, sort_keys=True)
        left = self.survivors(text)
        if left:
            raise SystemExit(f"refusing to write {path.name}: estate values survived scrubbing ({', '.join(left)})")
        path.write_text(text + "\n", encoding="utf-8")
        return text
