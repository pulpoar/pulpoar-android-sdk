#!/usr/bin/env bash
# Finishes a release whose tag and record landed but whose GitHub release did not (the Release workflow pushes the
# tag first). Run it from a clone of this repository, signed in to gh with write access:
#
#     scripts/finish_release.sh <tryon|skinai> <version>
#
# It never re-tags. It checks out the tag, verifies the CDN against the record the tag carries and reads the changelog
# section; any failure stops it before its only write, gh release create.
set -euo pipefail

[[ $# -eq 2 ]] || { echo "usage: $0 <tryon|skinai> <version>" >&2; exit 2; }
product=$1 version=$2
case $product in
  tryon) name=Try-On ;;
  skinai) name=SkinAI ;;
  *) echo "product must be tryon or skinai, not $product" >&2; exit 2 ;;
esac
tag="$product-$version"
cd "$(dirname "$0")/.."

[[ -z "$(git status --porcelain)" ]] || { echo "the working tree has changes; run this from a clean clone" >&2; exit 1; }
git fetch --tags origin
git -c advice.detachedHead=false checkout "$tag"

record="releases/$product/$version.json"
[[ -f "$record" ]] || { echo "$tag has no $record" >&2; exit 1; }
python3 scripts/verify_release.py "$version" --product "$product" --expect "$record"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
python3 scripts/release_guard.py notes "$product" "$version" "$work/notes.md"

flags=()
[[ "$version" == *-* ]] && flags+=(--prerelease --latest=false)
gh release create "$tag" --verify-tag --title "$name $version" --notes-file "$work/notes.md" ${flags[@]+"${flags[@]}"} # bash 3.2 (macOS): an empty array is unbound under set -u
