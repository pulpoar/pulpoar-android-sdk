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

    def build(self, engine_alignment=16384):
        engine = self.dir / "engine.aar"
        zip_with(engine, {"jni/arm64-v8a/libx.so": elf(engine_alignment)})
        payloads = {
            ("tryon-kit", self.VERSION): {"aar": b"kit", "pom": self.pom("tryon-kit", {"pulpo-module": f"[{self.ENGINE}]"}), "module": b"{}"},
            ("tryon-ui", self.VERSION): {"aar": b"ui", "pom": self.pom("tryon-ui", {"tryon-kit": self.VERSION}), "module": b"{}"},
            ("pulpo-module", self.ENGINE): {"aar": engine.read_bytes(), "pom": self.pom("pulpo-module", {})},
        }
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
        self.info = {"schema": 1, "version": self.VERSION, "engine": {"coordinate": f"com.pulpoar:pulpo-module:{self.ENGINE}"}, "artifacts": artifacts}
        self.publish_info()

    def publish_info(self):
        self.remote[f"tryon/{self.VERSION}/build-info.json"] = json.dumps(self.info).encode()

    def run_verify(self, expect=None):
        def fake(url, **_):
            key = url.replace("https://cdn.test/", "")
            key = key[len("maven/"):] if key.startswith("maven/") else key
            if key not in self.remote:
                raise OSError(f"404 {key}")
            return self.remote[key]
        with mock.patch.object(vr, "fetch", fake):
            return vr.verify(self.VERSION, "https://cdn.test", expect, self.dir / "work")

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


if __name__ == "__main__":
    unittest.main()
