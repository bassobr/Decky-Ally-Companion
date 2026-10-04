#!/usr/bin/env python3
"""Keep only the given plugins in an LSP manifest.ttl."""
import re
import sys

src, dst, keep = sys.argv[1], sys.argv[2], set(sys.argv[3:])
text = open(src, encoding="utf-8").read()
prefixes = [ln for ln in text.splitlines() if ln.startswith("@prefix")]
statements = re.split(r"\s\.\s*\n", text)
kept = []
for st in statements:
    st = st.strip()
    if not st or st.startswith("@prefix"):
        continue
    m = re.match(r"^plug:([A-Za-z0-9_]+)\b", st)
    if m and m.group(1) in keep and "lv2:Plugin" in st:
        kept.append(st + " .")
if len(kept) != len(keep):
    sys.exit(f"expected {len(keep)} plugin statements, found {len(kept)}")
open(dst, "w", encoding="utf-8").write("\n".join(prefixes) + "\n\n" + "\n\n".join(kept) + "\n")
print(f"manifest trimmed to {len(kept)} plugins")
