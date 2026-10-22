#!/usr/bin/env python3
"""Verifies a released Android SDK version exactly as a partner receives it from the CDN.

    verify_release.py 0.1.0 [--base-url URL] [--expect releases/0.1.0.json] [--work DIR]

It downloads tryon/<version>/build-info.json and every file it lists, then checks:
  * every listed path is a plain relative path inside the Maven repository (the manifest comes from the network),
  * sha256 and size of each file against build-info.json, and the published .sha256/.sha512 sidecars,
  * the POMs: tryon-ui needs exactly tryon-kit <version>, tryon-kit needs exactly the engine in build-info.json,
  * the engine AAR is 16 KB aligned (checked here, not trusted from build-info.json). A pre-release whose build-info.json
    records an unaligned engine only gets a warning; a final version never does,
  * with --expect (used automatically when releases/<version>.json exists next to this script), that build-info.json is identical to the copy recorded at release time, so a manifest that was
    replaced together with its files is caught.
Exits non-zero with every problem listed. Standard library only.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_apk_16kb  # noqa: E402

CDN = "https://assets.pulpoar.com/vision/pulpo-sdk/android"
USER_AGENT = "PulpoAR-SDK-CI/1.0"  # the CDN rejects Python's generic urllib agent
GROUP = "com.pulpoar"
ENGINE = "pulpo-module"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?$")
ARTIFACT_FILE = re.compile(r"^com/pulpoar/(?P<name>[a-z-]+)/(?P<version>[0-9A-Za-z.\-]+)/(?P<file>[0-9A-Za-z.\-]+)$")
POM_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def fetch(url, attempts=4, delay=5):
    """GET with retries (a fresh CDN object can lag a few seconds); 404 is final."""
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404 or attempt + 1 == attempts:
                raise
        except OSError:
            if attempt + 1 == attempts:
                raise
        time.sleep(delay)


def pom_dependencies(pom_bytes):
    """{artifactId: version} of the dependencies in the com.pulpoar group."""
    root = ET.fromstring(pom_bytes)
    found = {}
    for dep in root.findall("m:dependencies/m:dependency", POM_NS):
        if dep.findtext("m:groupId", namespaces=POM_NS) == GROUP:
            found[dep.findtext("m:artifactId", namespaces=POM_NS)] = dep.findtext("m:version", namespaces=POM_NS)
    return found


def safe_path(path, coordinate):
    """A manifest path is accepted only as com/pulpoar/<artifact>/<version>/<file> of its own coordinate."""
    match = ARTIFACT_FILE.match(path) if isinstance(path, str) else None
    group, name, version = coordinate.split(":")
    return bool(match) and ".." not in path and match["name"] == name and match["version"] == version and match["file"] not in (".", "..")


def check_info_shape(info, version):
    problems = []
    if info.get("schema") != 1:
        problems.append(f"build-info.json: unsupported schema {info.get('schema')!r}")
    if info.get("version") != version:
        problems.append(f"build-info.json: version is {info.get('version')!r}, expected {version}")
    coordinates = [a.get("coordinate") for a in info.get("artifacts", [])]
    engine = info.get("engine", {}).get("coordinate", "")
    for expected in (f"{GROUP}:tryon-kit:{version}", f"{GROUP}:tryon-ui:{version}", engine):
        if not expected or expected not in coordinates:
            problems.append(f"build-info.json: artifact {expected or 'engine'} is missing")
    if len(coordinates) != len(set(coordinates)):
        problems.append("build-info.json: an artifact is listed twice")
    for artifact in info.get("artifacts", []):
        coordinate = artifact.get("coordinate", "")
        if not re.fullmatch(r"com\.pulpoar:[a-z-]+:[0-9A-Za-z.\-]+", coordinate):
            problems.append(f"build-info.json: bad coordinate {coordinate!r}")
            continue
        for item in artifact.get("files", []):
            if not safe_path(item.get("path"), coordinate):
                problems.append(f"build-info.json: refusing path {item.get('path')!r} for {coordinate}")
        problems += check_inventory(artifact, coordinate)
    return problems


def check_inventory(artifact, coordinate):
    """The files every release of this artifact must list, once each: the manifest cannot omit what partners resolve."""
    group, name, version = coordinate.split(":")
    paths = [item.get("path") for item in artifact.get("files", [])]
    base = f"com/pulpoar/{name}/{version}/{name}-{version}"
    required = [f"{base}.aar", f"{base}.pom"] + ([] if name == ENGINE else [f"{base}.module"])
    problems = [f"build-info.json: {coordinate} does not list {path.rsplit('/', 1)[-1]}" for path in required if path not in paths]
    problems += [f"build-info.json: {path} is listed twice" for path in sorted({p for p in paths if paths.count(p) > 1})]
    return problems


def unaligned_allowed(version, info):
    """A pre-release may carry an unaligned engine, but only one that build-info.json admits to."""
    recorded = info.get("engine", {}).get("native_libraries_16kb_aligned", {})
    return "-" in version and any(aligned is False for aligned in recorded.values())


def verify(version, base_url=CDN, expect=None, work=None):
    """Returns the list of problems; empty means the release verifies."""
    if not SEMVER.match(version):
        return [f"{version!r} is not a release version"]
    maven = f"{base_url.rstrip('/')}/maven"
    try:
        raw_info = fetch(f"{base_url.rstrip('/')}/tryon/{version}/build-info.json")
        info = json.loads(raw_info)
    except (OSError, ValueError) as error:
        return [f"cannot read build-info.json for {version}: {error}"]
    problems = check_info_shape(info, version)
    if expect is not None:
        if json.loads(Path(expect).read_text()) != info:
            problems.append(f"build-info.json on the CDN differs from the recorded {expect}")
    if problems:
        return problems

    own_work = work is None
    work = Path(work or tempfile.mkdtemp(prefix="pulpo-verify-"))
    work.mkdir(parents=True, exist_ok=True)
    (work / "build-info.json").write_bytes(raw_info)
    try:
        files = {}
        for artifact in info["artifacts"]:
            for item in artifact["files"]:
                path = work / "maven" / item["path"]
                if (work / "maven").resolve() not in path.resolve().parents:
                    problems.append(f"{item['path']}: outside the repository")
                    continue
                try:
                    data = fetch(f"{maven}/{item['path']}")
                except OSError as error:
                    problems.append(f"{item['path']}: {error}")
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                files[item["path"]] = path
                if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    problems.append(f"{item['path']}: differs from build-info.json")
                for algorithm in ("sha256", "sha512"):
                    try:
                        published = fetch(f"{maven}/{item['path']}.{algorithm}").decode().split()[0].lower()
                    except (OSError, IndexError) as error:
                        problems.append(f"{item['path']}.{algorithm}: {error or 'empty'}")
                        continue
                    if published != hashlib.new(algorithm, data).hexdigest():
                        problems.append(f"{item['path']}.{algorithm}: does not match the file")

        _, engine_name, engine_version = info["engine"]["coordinate"].split(":")
        for name, expected in (("tryon-ui", {"tryon-kit": version}), ("tryon-kit", {"pulpo-module": f"[{engine_version}]"})):
            pom = files.get(f"com/pulpoar/{name}/{version}/{name}-{version}.pom")
            if pom is None:
                problems.append(f"{name}-{version}.pom was not downloaded")
                continue
            actual = {k: v for k, v in pom_dependencies(pom.read_bytes()).items() if k in expected or k == "pulpo-module"}
            if actual != expected:
                problems.append(f"{name} POM depends on {actual}, expected {expected}")
        aar = files.get(f"com/pulpoar/{engine_name}/{engine_version}/{engine_name}-{engine_version}.aar")
        if aar is None:
            problems.append("engine AAR was not downloaded")
        else:
            alignment = [f"engine {p}" for p in check_apk_16kb.check_archive(aar, ("jni/",), zip_offsets=False)]
            if alignment and unaligned_allowed(version, info):
                print(f"WARN {version} is a pre-release with an engine that is not 16 KB aligned (recorded in build-info.json): "
                      "fine for integration, not for Google Play uploads", file=sys.stderr)
            else:
                problems += alignment
        return problems
    finally:
        if own_work:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version")
    parser.add_argument("--base-url", default=CDN, help="CDN folder holding maven/ and tryon/ (default: %(default)s)")
    parser.add_argument("--expect", type=Path, help="recorded build-info.json (releases/<version>.json) the CDN copy must equal")
    parser.add_argument("--work", type=Path, help="keep downloads here (default: a temporary folder)")
    args = parser.parse_args(argv)
    if args.expect is None:
        recorded = Path(__file__).resolve().parent.parent / "releases" / f"{args.version}.json"
        if recorded.is_file():
            args.expect = recorded
            print(f"comparing with the recorded {recorded.name}")
    problems = verify(args.version, args.base_url, args.expect, args.work)
    for problem in problems:
        print(f"FAIL {problem}")
    print(f"{'FAILED' if problems else 'VERIFIED'} {args.version}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
