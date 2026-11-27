import hashlib
import json
import shutil
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import check_apk_16kb as apk
import release_guard as rg
import verify_release as vr


def elf(alignment, wide=True):
    """A minimal ELF with a single PT_LOAD segment of the given alignment."""
    if wide:
        header = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9) + struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, 0, 64, 0, 0, 64, 56, 1, 64, 0, 0)
        return header + struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, 0x100, 0x100, alignment)
    header = b"\x7fELF" + bytes([1, 1, 1]) + bytes(9) + struct.pack("<HHIIIIIHHHHHH", 3, 40, 1, 0, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    return header + struct.pack("<IIIIIIII", 1, 0, 0, 0, 0x100, 0x100, 5, alignment)


def zip_with(path, libraries, stored_aligned=True):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, data in libraries.items():
            archive.writestr(name, data)
    return path


class ElfTests(unittest.TestCase):
    def test_alignments(self):
        self.assertEqual(apk.load_alignments(elf(16384)), [16384])
        self.assertEqual(apk.load_alignments(elf(4096)), [4096])
        self.assertEqual(apk.load_alignments(elf(65536, wide=False)), [65536])

    def test_rejects_non_elf(self):
        with self.assertRaises(ValueError):
            apk.load_alignments(b"not an elf at all, really")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def test_aligned_libraries_pass_when_compressed(self):
        path = self.dir / "a.apk"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("lib/arm64-v8a/libx.so", elf(16384))
        self.assertEqual(apk.check_archive(path), [])

    def test_32_bit_libraries_are_not_checked(self):
        path = self.dir / "a.apk"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("lib/arm64-v8a/libx.so", elf(16384))
            archive.writestr("lib/armeabi-v7a/libx.so", elf(4096, wide=False))
        self.assertEqual([], apk.check_archive(path))

    def test_misaligned_segment_fails(self):
        path = zip_with(self.dir / "a.apk", {"lib/arm64-v8a/libx.so": elf(4096)})
        self.assertTrue(any("alignment is 4096" in p for p in apk.check_archive(path)))

    def test_stored_library_at_unaligned_offset_fails(self):
        path = zip_with(self.dir / "a.apk", {"lib/arm64-v8a/libx.so": elf(16384)})
        self.assertTrue(any("file offset" in p for p in apk.check_archive(path)))

    def test_stored_library_padded_to_page_passes(self):
        path = self.dir / "a.apk"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
            info = zipfile.ZipInfo("lib/arm64-v8a/libx.so")
            header = 30 + len(info.filename)
            info.extra = b"\x00" * ((-header) % apk.PAGE)
            # The extra field must be valid zip extra data: id 0xD935 (Android alignment padding).
            info.extra = struct.pack("<HH", 0xD935, len(info.extra) - 4) + info.extra[4:] if len(info.extra) >= 4 else info.extra
            archive.writestr(info, elf(16384))
        self.assertEqual(apk.check_archive(path), [])

    def test_no_libraries_fails(self):
        path = zip_with(self.dir / "a.apk", {"classes.dex": b"dex"})
        self.assertTrue(apk.check_archive(path))


class VerifyReleaseTests(unittest.TestCase):
    VERSION = "1.2.3"
    ENGINE = "0.0.9"

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.remote = {}
        self.build()

    def pom(self, name, deps):
        body = "".join(f"<dependency><groupId>com.pulpoar</groupId><artifactId>{a}</artifactId><version>{v}</version></dependency>" for a, v in deps.items())
        return f'<project xmlns="http://maven.apache.org/POM/4.0.0"><artifactId>{name}</artifactId><dependencies>{body}</dependencies></project>'.encode()

    PRODUCT, ENGINE_NAME = "tryon", "pulpo-module"

    def payloads(self, engine_aar):
        return {
            ("tryon-kit", self.VERSION): {"aar": b"kit", "pom": self.pom("tryon-kit", {"pulpo-module": f"[{self.ENGINE}]"}), "module": b"{}"},
            ("tryon-ui", self.VERSION): {"aar": b"ui", "pom": self.pom("tryon-ui", {"tryon-kit": self.VERSION}), "module": b"{}"},
            ("pulpo-module", self.ENGINE): {"aar": engine_aar, "pom": self.pom("pulpo-module", {})},
        }

    def build(self, engine_alignment=16384):
        engine = self.dir / "engine.aar"
        zip_with(engine, {"jni/arm64-v8a/libx.so": elf(engine_alignment)})
        payloads = self.payloads(engine.read_bytes())
        artifacts = []
        for (name, version), files in payloads.items():
            listing = []
            for ext, data in files.items():
                path = f"com/pulpoar/{name}/{version}/{name}-{version}.{ext}"
                self.remote[path] = data
                for algorithm in ("sha256", "sha512"):
                    self.remote[f"{path}.{algorithm}"] = hashlib.new(algorithm, data).hexdigest().encode()
                listing.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            artifacts.append({"coordinate": f"com.pulpoar:{name}:{version}", "files": listing})
        self.info = {"schema": 1, "version": self.VERSION, "engine": {"coordinate": f"com.pulpoar:{self.ENGINE_NAME}:{self.ENGINE}"}, "artifacts": artifacts}
        self.publish_info()

    def publish_info(self):
        self.remote[f"{self.PRODUCT}/{self.VERSION}/build-info.json"] = json.dumps(self.info).encode()

    def run_verify(self, expect=None, product=None):
        def fake(url, **_):
            key = url.replace("https://cdn.test/", "")
            key = key[len("maven/"):] if key.startswith("maven/") else key
            if key not in self.remote:
                raise OSError(f"404 {key}")
            return self.remote[key]
        with mock.patch.object(vr, "fetch", fake):
            return vr.verify(self.VERSION, "https://cdn.test", expect, self.dir / "work", product or self.PRODUCT)

    def test_good_release_verifies(self):
        self.assertEqual(self.run_verify(), [])

    def test_tampered_file_fails(self):
        self.remote[f"com/pulpoar/tryon-ui/{self.VERSION}/tryon-ui-{self.VERSION}.aar"] = b"evil"
        self.assertTrue(any("differs from build-info" in p for p in self.run_verify()))

    def test_tampered_sidecar_fails(self):
        self.remote[f"com/pulpoar/tryon-ui/{self.VERSION}/tryon-ui-{self.VERSION}.aar.sha256"] = b"0" * 64
        self.assertTrue(any(".sha256: does not match" in p for p in self.run_verify()))

    def test_missing_sidecar_fails(self):
        del self.remote[f"com/pulpoar/tryon-ui/{self.VERSION}/tryon-ui-{self.VERSION}.aar.sha512"]
        self.assertTrue(any(".sha512" in p for p in self.run_verify()))

    def test_a_pre_release_may_carry_an_engine_it_admits_is_unaligned(self):
        self.VERSION = "1.2.3-rc.1"
        self.remote.clear()
        self.build(engine_alignment=4096)
        self.info["engine"]["native_libraries_16kb_aligned"] = {"jni/arm64-v8a/libx.so": False}
        self.publish_info()
        self.assertEqual(self.run_verify(), [])

    def test_a_pre_release_cannot_hide_an_unaligned_engine(self):
        self.VERSION = "1.2.3-rc.1"
        self.remote.clear()
        self.build(engine_alignment=4096)
        self.info["engine"]["native_libraries_16kb_aligned"] = {"jni/arm64-v8a/libx.so": True}
        self.publish_info()
        self.assertTrue(any(p.startswith("engine ") for p in self.run_verify()))

    def test_a_final_version_never_may(self):
        self.build(engine_alignment=4096)
        self.info["engine"]["native_libraries_16kb_aligned"] = {"jni/arm64-v8a/libx.so": False}
        self.publish_info()
        self.assertTrue(any(p.startswith("engine ") for p in self.run_verify()))

    def test_wrong_engine_pin_fails(self):
        self.remote[f"com/pulpoar/tryon-kit/{self.VERSION}/tryon-kit-{self.VERSION}.pom"] = self.pom("tryon-kit", {"pulpo-module": "[9.9.9]"})
        self.assertTrue(any("POM" in p for p in self.run_verify()))

    def test_unaligned_engine_fails(self):
        self.build(engine_alignment=4096)
        self.assertTrue(any(p.startswith("engine ") for p in self.run_verify()))

    def test_manifest_paths_cannot_escape_the_download_folder(self):
        for evil in ("../../escaped.txt", "/tmp/escaped.txt", "com/pulpoar/tryon-kit/../../../x", "com/pulpoar/tryon-kit/1.2.3/../../../../x"):
            self.build()
            self.info["artifacts"][0]["files"].append({"path": evil, "sha256": "0" * 64, "bytes": 1})
            self.publish_info()
            self.remote[evil] = b"x"
            problems = self.run_verify()
            self.assertTrue(any("refusing path" in p for p in problems), evil)
            self.assertFalse((self.dir / "escaped.txt").exists())
            self.assertFalse(Path("/tmp/escaped.txt").exists())

    def test_path_of_another_artifact_is_refused(self):
        self.info["artifacts"][0]["files"].append({"path": f"com/pulpoar/tryon-ui/{self.VERSION}/x.aar", "sha256": "0" * 64, "bytes": 1})
        self.publish_info()
        self.assertTrue(any("refusing path" in p for p in self.run_verify()))

    def test_manifest_must_equal_the_recorded_copy(self):
        recorded = self.dir / "recorded.json"
        recorded.write_text(json.dumps(self.info))
        self.assertEqual(self.run_verify(recorded), [])
        # Replace a file and the manifest together: only the recorded copy exposes it.
        path = f"com/pulpoar/tryon-ui/{self.VERSION}/tryon-ui-{self.VERSION}.aar"
        self.remote[path] = b"evil"
        for item in self.info["artifacts"][1]["files"]:
            if item["path"] == path:
                item.update(sha256=hashlib.sha256(b"evil").hexdigest(), bytes=4)
        self.remote[path + ".sha256"] = hashlib.sha256(b"evil").hexdigest().encode()
        self.remote[path + ".sha512"] = hashlib.sha512(b"evil").hexdigest().encode()
        self.publish_info()
        self.assertEqual(self.run_verify(), [])
        self.assertTrue(any("differs from the recorded" in p for p in self.run_verify(recorded)))

    def test_a_manifest_that_omits_required_files_is_refused(self):
        for ext in ("aar", "pom", "module"):
            self.build()
            self.info["artifacts"][0]["files"] = [f for f in self.info["artifacts"][0]["files"] if not f["path"].endswith("." + ext)]
            self.publish_info()
            self.assertTrue(any(f"does not list tryon-kit-{self.VERSION}.{ext}" in p for p in self.run_verify()), ext)

    def test_an_engine_without_its_aar_is_refused(self):
        self.info["artifacts"][2]["files"] = [f for f in self.info["artifacts"][2]["files"] if not f["path"].endswith(".aar")]
        self.publish_info()
        self.assertTrue(any("does not list pulpo-module" in p for p in self.run_verify()))

    def test_duplicate_entries_are_refused(self):
        self.info["artifacts"][1]["files"].append(dict(self.info["artifacts"][1]["files"][0]))
        self.publish_info()
        self.assertTrue(any("listed twice" in p for p in self.run_verify()))
        self.build()
        self.info["artifacts"].append(dict(self.info["artifacts"][0]))
        self.publish_info()
        self.assertTrue(any("an artifact is listed twice" in p for p in self.run_verify()))

    def test_rejects_non_release_version(self):
        self.assertTrue(vr.verify("main"))


class SkinAIVerifyReleaseTests(unittest.TestCase):
    """A SkinAI release: skinai-kit pinning pulpo-skinai, and skinai-ui on it. Reuses the Try-On fixture, not its Try-On-only tests."""
    VERSION, PRODUCT, ENGINE_NAME, ENGINE = "1.2.3", "skinai", "pulpo-skinai", "0.2.0"
    setUp, pom, publish_info, run_verify = (VerifyReleaseTests.setUp, VerifyReleaseTests.pom,
                                            VerifyReleaseTests.publish_info, VerifyReleaseTests.run_verify)

    def payloads(self, engine_aar):
        return {
            ("skinai-kit", self.VERSION): {"aar": b"kit", "pom": self.pom("skinai-kit", {"pulpo-skinai": f"[{self.ENGINE}]"}), "module": b"{}"},
            ("skinai-ui", self.VERSION): {"aar": b"ui", "pom": self.pom("skinai-ui", {"skinai-kit": self.VERSION}), "module": b"{}"},
            ("pulpo-skinai", self.ENGINE): {"aar": engine_aar, "pom": self.pom("pulpo-skinai", {})},
        }

    def build(self, engine_alignment=16384):
        VerifyReleaseTests.build(self, engine_alignment)
        self.info["product"] = "skinai"
        self.publish_info()

    def test_good_release_verifies(self):
        self.assertEqual(self.run_verify(), [])

    def test_wrong_engine_pin_fails(self):
        self.remote[f"com/pulpoar/skinai-kit/{self.VERSION}/skinai-kit-{self.VERSION}.pom"] = self.pom("skinai-kit", {"pulpo-skinai": "[9.9.9]"})
        self.assertTrue(any("POM" in p for p in self.run_verify()))

    def test_ui_on_another_kit_version_fails(self):
        self.remote[f"com/pulpoar/skinai-ui/{self.VERSION}/skinai-ui-{self.VERSION}.pom"] = self.pom("skinai-ui", {"skinai-kit": "9.9.9"})
        self.assertTrue(any("skinai-ui POM" in p for p in self.run_verify()))

    def drop_ui(self):
        self.info["artifacts"] = [a for a in self.info["artifacts"] if ":skinai-ui:" not in a["coordinate"]]
        self.publish_info()

    def test_a_release_without_the_ui_fails(self):
        self.drop_ui()
        self.assertIn(f"build-info.json: artifact com.pulpoar:skinai-ui:{self.VERSION} is missing", self.run_verify())

    def test_a_release_from_before_the_ui_verifies_with_the_kit_alone(self):
        self.VERSION = "0.2.0-rc.1"  # published with skinai-kit only
        self.build()
        self.drop_ui()
        self.assertEqual(self.run_verify(), [])

    def test_unaligned_engine_fails(self):
        self.build(engine_alignment=4096)
        self.assertTrue(any(p.startswith("engine ") for p in self.run_verify()))

    def test_a_try_on_engine_is_refused(self):
        self.info["engine"]["coordinate"] = f"com.pulpoar:pulpo-module:{self.ENGINE}"
        self.publish_info()
        self.assertTrue(any("engine is" in p for p in self.run_verify()))

    def test_a_manifest_of_the_other_product_is_refused(self):
        del self.info["product"]  # what a Try-On manifest looks like
        self.publish_info()
        self.assertTrue(any("product is 'tryon'" in p for p in self.run_verify()))

    def test_the_product_comes_from_the_recorded_release(self):
        recorded = self.dir / f"{self.VERSION}.json"
        recorded.write_text(json.dumps(self.info))
        seen = {}
        with mock.patch.object(vr, "verify", lambda *a: seen.setdefault("product", a[4]) and []):
            self.assertEqual(vr.main([self.VERSION, "--expect", str(recorded)]), 0)
        self.assertEqual(seen["product"], "skinai")

    def test_a_product_that_contradicts_the_recorded_release_fails(self):
        recorded = self.dir / f"{self.VERSION}.json"
        recorded.write_text(json.dumps(self.info))
        with mock.patch.object(vr, "verify", lambda *a: []), self.assertRaises(SystemExit) as stop:
            vr.main([self.VERSION, "--product", "tryon", "--expect", str(recorded)])
        self.assertEqual(stop.exception.code, 2)

    def test_a_version_alone_does_not_name_a_release(self):
        with mock.patch.object(vr, "verify", lambda *a: []), self.assertRaises(SystemExit) as stop:
            vr.main([self.VERSION])
        self.assertEqual(stop.exception.code, 2)


class Repository:
    """A clone's releases/ and CHANGELOG.md as they are at the cutover: legacy flat records, then the product folders."""

    CHANGELOG = """# Changelog

## Unreleased

## Try-On 0.2.0

Try-On notes.

## SkinAI 0.2.0-rc.1

SkinAI preview notes.

## Try-On 0.1.0

First.
"""

    def make_repository(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "releases").mkdir()
        self.flat("0.2.0", {"version": "0.2.0", "product": "tryon"})
        self.flat("0.2.0-rc.1", {"version": "0.2.0-rc.1", "product": "skinai"})
        self.flat("0.1.0", {"version": "0.1.0"})  # Try-On manifests from before SkinAI name no product
        (self.root / "CHANGELOG.md").write_text(self.CHANGELOG)

    def flat(self, version, info):
        (self.root / "releases" / f"{version}.json").write_text(json.dumps(info))

    def nested(self, product, version):
        (self.root / "releases" / product).mkdir(exist_ok=True)
        path = self.root / "releases" / product / f"{version}.json"
        path.write_text(json.dumps({"version": version, "product": product}))
        return path

    def changelog(self, text):
        (self.root / "CHANGELOG.md").write_text(self.CHANGELOG.replace("## Unreleased\n", "## Unreleased\n" + text))


class ReleaseGuardTests(Repository, unittest.TestCase):
    def setUp(self):
        self.make_repository()

    def check(self, product, version):
        return rg.problems_for_new(product, version, self.root)

    def test_skinai_0_2_0_is_new_next_to_the_legacy_try_on_0_2_0(self):
        self.assertIsNone(rg.record("skinai", "0.2.0", self.root))
        self.assertEqual(rg.record("tryon", "0.2.0", self.root), self.root / "releases" / "0.2.0.json")
        self.assertEqual(self.check("skinai", "0.2.0"), ["CHANGELOG.md has no '## SkinAI 0.2.0' section"])
        self.changelog("\n## SkinAI 0.2.0\n\nFinal.\n\n")
        self.assertEqual(self.check("skinai", "0.2.0"), [])

    def test_a_released_version_is_refused_in_either_layout(self):
        self.assertIn("already released (recorded in releases/0.2.0.json)", self.check("tryon", "0.2.0")[0])
        self.assertIn("already released", self.check("tryon", "0.1.0")[0])
        self.assertIn("already released", self.check("skinai", "0.2.0-rc.1")[0])
        self.nested("skinai", "0.2.0")
        self.assertIn("recorded in releases/skinai/0.2.0.json", self.check("skinai", "0.2.0")[0])

    def test_one_version_under_both_products_is_two_releases(self):
        tryon, skinai = self.nested("tryon", "9.9.9"), self.nested("skinai", "9.9.9")
        self.assertEqual(rg.record("tryon", "9.9.9", self.root), tryon)
        self.assertEqual(rg.record("skinai", "9.9.9", self.root), skinai)
        listed = {(p, v) for p, v, _ in rg.records(self.root)}
        self.assertEqual(listed, {("tryon", "0.2.0"), ("skinai", "0.2.0-rc.1"), ("tryon", "0.1.0"),
                                  ("tryon", "9.9.9"), ("skinai", "9.9.9")})

    def test_the_heading_matches_literally(self):
        self.changelog("\n## Try-On 0x3x0\n\nNot 0.3.0.\n\n")
        self.assertEqual(self.check("tryon", "0.3.0"), ["CHANGELOG.md has no '## Try-On 0.3.0' section"])
        self.assertEqual(self.check("skinai", "0.1.0"), ["CHANGELOG.md has no '## SkinAI 0.1.0' section"])

    def test_an_empty_section_is_refused(self):
        self.changelog("\n## Try-On 0.3.0\n\n\n")
        self.assertEqual(self.check("tryon", "0.3.0"), ["CHANGELOG.md's '## Try-On 0.3.0' section is empty"])
        self.assertEqual(rg.main(["notes", "tryon", "0.3.0", str(self.root / "notes.md")], self.root), 1)
        self.assertFalse((self.root / "notes.md").exists())

    def test_notes_are_the_section_alone(self):
        out = self.root / "notes.md"
        self.assertEqual(rg.main(["notes", "skinai", "0.2.0-rc.1", str(out)], self.root), 0)
        self.assertEqual(out.read_text(), "SkinAI preview notes.\n")

    def test_bad_input_is_refused(self):
        self.assertIn("product must be", self.check("", "1.0.0")[0])
        self.assertIn("version must look like", self.check("tryon", "v1.0.0")[0])

    def test_audit_needs_a_section_for_every_record(self):
        self.assertEqual(rg.main(["audit"], self.root), 0)
        self.nested("skinai", "0.2.0")
        self.assertEqual(rg.main(["audit"], self.root), 1)

    def test_the_verifier_finds_only_its_own_products_record(self):
        seen = []
        with mock.patch.object(rg, "ROOT", self.root), mock.patch.object(vr, "verify", lambda *a: seen.append(a) or []):
            self.assertEqual(vr.main(["0.2.0", "--product", "skinai"]), 0)
            self.assertEqual(vr.main(["0.2.0", "--product", "tryon"]), 0)
        self.assertEqual([(a[2], a[4]) for a in seen], [(None, "skinai"), (self.root / "releases" / "0.2.0.json", "tryon")])


class FinishReleaseTests(Repository, unittest.TestCase):
    """finish_release.sh with git, gh and python3 stubbed: its only write, gh release create, follows every check."""

    STUB = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$STUB_LOG"
case "$(basename "$0") $*" in *"$STUB_FAIL"*) [[ -n "$STUB_FAIL" ]] && exit 1 ;; esac
[[ "$(basename "$0") $1" == "git status" ]] && printf %s "$STUB_DIRTY"
exit 0
"""

    def setUp(self):
        self.make_repository()
        (self.root / "scripts").mkdir()
        shutil.copy(Path(__file__).with_name("finish_release.sh"), self.root / "scripts")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ("git", "gh", "python3"):
            (self.bin / tool).write_text(self.STUB)
            (self.bin / tool).chmod(0o755)
        self.nested("skinai", "0.2.0")
        self.nested("tryon", "9.9.9-rc.1")

    def finish(self, product, version, fail="", dirty=""):
        log = self.root / "log"
        log.write_text("")
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "STUB_LOG": str(log), "STUB_FAIL": fail, "STUB_DIRTY": dirty}
        import subprocess
        code = subprocess.run(["bash", str(self.root / "scripts" / "finish_release.sh"), product, version], env=env,
                              capture_output=True).returncode
        return code, log.read_text().splitlines()

    def test_a_good_release_is_announced_once_under_its_tag(self):
        code, calls = self.finish("skinai", "0.2.0")
        self.assertEqual(code, 0)
        self.assertIn("git -c advice.detachedHead=false checkout skinai-0.2.0", calls)
        self.assertIn("python3 scripts/verify_release.py 0.2.0 --product skinai --expect releases/skinai/0.2.0.json", calls)
        self.assertTrue(calls[-1].startswith("gh release create skinai-0.2.0 --verify-tag --title SkinAI 0.2.0 --notes-file "))
        self.assertFalse(calls[-1].endswith("--latest=false"))

    def test_a_pre_release_is_never_latest(self):
        code, calls = self.finish("tryon", "9.9.9-rc.1")
        self.assertEqual(code, 0)
        self.assertTrue(calls[-1].endswith("--prerelease --latest=false"))

    def test_any_failure_makes_no_release(self):
        for fail in ("git fetch", "checkout", "verify_release.py", "release_guard.py notes"):
            code, calls = self.finish("skinai", "0.2.0", fail=fail)
            self.assertNotEqual(code, 0, fail)
            self.assertFalse([c for c in calls if c.startswith("gh ")], fail)

    def test_no_release_without_the_record_a_dirty_tree_or_a_known_product(self):
        for args in (("tryon", "0.2.0"), ("skinai", "0.2.0", "", " M README.md"), ("studio", "0.2.0")):
            code, calls = self.finish(*args)
            self.assertNotEqual(code, 0, args)
            self.assertFalse([c for c in calls if c.startswith("gh ")], args)


if __name__ == "__main__":
    unittest.main()
