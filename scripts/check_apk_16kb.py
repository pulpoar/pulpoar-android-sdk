#!/usr/bin/env python3
"""Checks that an APK (or AAR) works on devices with 16 KB memory pages (Android 15+).

Two rules, both from Google's guidance:
  * every PT_LOAD segment of every 64-bit native library has p_align >= 16384, and
  * a native library stored uncompressed in the APK starts at a multiple of 16384 within the file
    (compressed libraries are extracted at install time and need nothing).
Only arm64-v8a and x86_64 are checked: 16 KB page devices are 64-bit only, and Google Play's requirement covers
64-bit libraries. armeabi-v7a and x86 libraries are skipped.
"""
import argparse
import struct
import sys
import zipfile

PAGE = 16384
ABIS_64 = ("arm64-v8a", "x86_64")


def load_alignments(data):
    """p_align of every PT_LOAD segment of an ELF image."""
    if data[:4] != b"\x7fELF" or data[4] not in (1, 2) or data[5] not in (1, 2):
        raise ValueError("not an ELF file")
    wide = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    if wide:
        phoff, phsize, phcount = struct.unpack_from(endian + "Q", data, 32)[0], *struct.unpack_from(endian + "HH", data, 54)
        fmt, align_at = endian + "IIQQQQQQ", 7
    else:
        phoff, phsize, phcount = struct.unpack_from(endian + "I", data, 28)[0], *struct.unpack_from(endian + "HH", data, 42)
        fmt, align_at = endian + "IIIIIIII", 7
    alignments = []
    for index in range(phcount):
        entry = struct.unpack_from(fmt, data, phoff + index * phsize)
        if entry[0] == 1:
            alignments.append(entry[align_at])
    if not alignments:
        raise ValueError("ELF has no PT_LOAD segments")
    return alignments


def stored_data_offset(archive_bytes, info):
    """Where the (uncompressed) data of a zip entry starts in the file."""
    signature, = struct.unpack_from("<I", archive_bytes, info.header_offset)
    if signature != 0x04034B50:
        raise ValueError(f"{info.filename}: bad local header")
    name_length, extra_length = struct.unpack_from("<HH", archive_bytes, info.header_offset + 26)
    return info.header_offset + 30 + name_length + extra_length


def check_archive(path, prefixes=("lib/",), zip_offsets=True):
    """Returns a list of problems; empty means the archive is fine.

    `zip_offsets` is for APKs only: an AAR is unpacked by Gradle, never mapped from the zip.
    """
    problems = []
    with open(path, "rb") as handle:
        raw = handle.read()
    found = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.filename.endswith(".so") or not info.filename.startswith(prefixes):
                continue
            if info.filename.split("/")[1] not in ABIS_64:
                continue
            found += 1
            try:
                weakest = min(load_alignments(archive.read(info)))
            except ValueError as error:
                problems.append(f"{info.filename}: {error}")
                continue
            if weakest < PAGE:
                problems.append(f"{info.filename}: LOAD segment alignment is {weakest}, needs >= {PAGE}")
            if zip_offsets and info.compress_type == zipfile.ZIP_STORED and stored_data_offset(raw, info) % PAGE:
                problems.append(f"{info.filename}: stored at a file offset that is not a multiple of {PAGE}")
    if not found:
        problems.append(f"{path}: no native libraries found (expected under {', '.join(prefixes)})")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archives", nargs="+", help="APK files (AARs with --aar)")
    parser.add_argument("--aar", action="store_true", help="libraries live under jni/ and zip offsets are not checked")
    args = parser.parse_args(argv)
    failed = False
    for path in args.archives:
        problems = check_archive(path, ('jni/',), False) if args.aar else check_archive(path)
        for problem in problems:
            print(f"FAIL {problem}")
        print(f"{'FAIL' if problems else 'ok  '} {path}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
