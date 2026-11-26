#!/usr/bin/env python3
"""The release records and changelog sections of this repository, for the release workflow, CI and finish_release.sh.

    release_guard.py check <product> <version>        refuse a released (product, version); require its changelog section
    release_guard.py notes <product> <version> <out>  write its changelog section to <out>; refuse an empty one
    release_guard.py records                          print "<product> <version> <path>" for every recorded release
    release_guard.py audit                            every recorded release has a non-empty changelog section

Each product has its own version line. A release is recorded as releases/<product>/<version>.json; the releases made
before that (Try-On up to 0.2.0, SkinAI 0.2.0-rc.1) stay at releases/<version>.json, and their product is the one their
manifest names (none means Try-On). Changelog sections are headed exactly "## <Name> <version>", e.g. "## Try-On 0.2.0".
Standard library only.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = {"tryon": "Try-On", "skinai": "SkinAI"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?$")


def manifest_product(path):
    """The product a recorded build-info.json releases; Try-On manifests from before SkinAI name none."""
    return json.loads(Path(path).read_text()).get("product", "tryon")


def record(product, version, root=ROOT):
    """The recorded manifest of (product, version), or None. A legacy flat record counts only for its own product:
    releases/0.2.0.json is Try-On's and says nothing about SkinAI 0.2.0."""
    nested = root / "releases" / product / f"{version}.json"
    if nested.is_file():
        return nested
    flat = root / "releases" / f"{version}.json"
    if flat.is_file() and manifest_product(flat) == product:
        return flat
    return None


def records(root=ROOT):
    """(product, version, path) of every recorded release, in both layouts."""
    found = [(manifest_product(p), p.stem, p) for p in sorted((root / "releases").glob("*.json"))]
    found += [(p.parent.name, p.stem, p) for p in sorted((root / "releases").glob("*/*.json")) if p.parent.name in NAMES]
    return found


def section(product, version, root=ROOT):
    """The changelog section's text, or None without a heading. The heading matches literally, never as a pattern."""
    heading, lines, inside = f"## {NAMES[product]} {version}", [], None
    for line in (root / "CHANGELOG.md").read_text().splitlines():
        if line == heading:
            inside = True
        elif line.startswith("## "):
            if inside:
                break
        elif inside:
            lines.append(line)
    return "\n".join(lines).strip() + "\n" if inside else None


def problems_for_new(product, version, root=ROOT):
    if product not in NAMES:
        return [f"product must be one of {', '.join(NAMES)}, not {product!r}"]
    if not SEMVER.match(version):
        return [f"version must look like 1.2.3 or 1.2.3-rc.1, not {version!r}"]
    found = record(product, version, root)
    if found:
        return [f"{NAMES[product]} {version} was already released (recorded in {found.relative_to(root)})"]
    return section_problems(product, version, root)


def section_problems(product, version, root=ROOT):
    text = section(product, version, root)
    heading = f"## {NAMES[product]} {version}"
    if text is None:
        return [f"CHANGELOG.md has no '{heading}' section"]
    return [] if text.strip() else [f"CHANGELOG.md's '{heading}' section is empty"]


def main(argv=None, root=ROOT):
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else ""
    if command == "check" and len(args) == 3:
        problems = problems_for_new(args[1], args[2], root)
    elif command == "notes" and len(args) == 4:
        problems = section_problems(args[1], args[2], root) if args[1] in NAMES else [f"unknown product {args[1]!r}"]
        if not problems:
            Path(args[3]).write_text(section(args[1], args[2], root))
    elif command == "records" and len(args) == 1:
        for product, version, path in records(root):
            print(product, version, path.relative_to(root))
        return 0
    elif command == "audit" and len(args) == 1:
        problems = [p for product, version, _ in records(root) for p in section_problems(product, version, root)]
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
