#!/usr/bin/env python3
"""
generate_firmware_manifest.py
TRACKFRAME XL — Firmware Manifest Generator

Scans firmware/teensy/ and firmware/esp32/ for the latest .hex and .bin files,
computes SHA-256 hashes, extracts version numbers from filenames, and writes
a fresh firmware-manifest.json to the repo root.

Run automatically by GitHub Actions on every push that modifies firmware/.
Can also be run locally: python3 scripts/generate_firmware_manifest.py

Expected firmware filename formats:
  Teensy : trackframe-teensy-v{MAJOR}.{MINOR}.{PATCH}.hex
  ESP32  : trackframe-esp32-v{MAJOR}.{MINOR}.{PATCH}.bin

If multiple versions exist, the highest semver wins.
Old firmware files should be deleted from the repo when no longer needed.
"""

import json
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

REPO_ROOT       = Path(__file__).parent.parent
FIRMWARE_DIR    = REPO_ROOT / "firmware"
TEENSY_DIR      = FIRMWARE_DIR / "teensy"
ESP32_DIR       = FIRMWARE_DIR / "esp32"
OUTPUT_FILE     = REPO_ROOT / "firmware-manifest.json"

REPO_BASE_URL   = "https://raw.githubusercontent.com/JoshCBruce/TrackFrame/main"

# Regex patterns for version extraction from filenames
TEENSY_PATTERN  = re.compile(r"trackframe-teensy-v(\d+\.\d+\.\d+)\.hex$", re.IGNORECASE)
ESP32_PATTERN   = re.compile(r"trackframe-esp32-v(\d+\.\d+\.\d+)\.bin$", re.IGNORECASE)

# Changelog file locations (optional — one per firmware directory)
# If present, its content is embedded in the manifest for display in the companion app.
TEENSY_CHANGELOG = TEENSY_DIR / "CHANGELOG.md"
ESP32_CHANGELOG  = ESP32_DIR  / "CHANGELOG.md"

# Maximum characters to embed from changelog (keeps manifest size reasonable)
CHANGELOG_MAX_CHARS = 500

# ── Helpers ───────────────────────────────────────────────────────────────────

def sha256_of_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file, reading in 64 KB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Convert 'MAJOR.MINOR.PATCH' string to comparable tuple of ints."""
    parts = version_str.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def version_str(tup: tuple[int, int, int]) -> str:
    return f"{tup[0]}.{tup[1]}.{tup[2]}"


def find_latest_firmware(directory: Path, pattern: re.Pattern) -> tuple[Path, str] | None:
    """
    Scan directory for files matching pattern.
    Returns (path, version_string) for the file with the highest semver,
    or None if no matching files found.
    """
    if not directory.exists():
        return None

    candidates = []
    for f in directory.iterdir():
        match = pattern.match(f.name)
        if match:
            ver_str = match.group(1)
            try:
                ver_tuple = parse_version(ver_str)
                candidates.append((ver_tuple, ver_str, f))
            except (ValueError, IndexError):
                print(f"  WARNING: Could not parse version from {f.name}", file=sys.stderr)

    if not candidates:
        return None

    # Sort descending by semver tuple, pick highest
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_tuple, best_ver_str, best_path = candidates[0]

    if len(candidates) > 1:
        others = [c[1] for c in candidates[1:]]
        print(f"  INFO: Multiple versions found in {directory.name}/. "
              f"Using v{best_ver_str}. Others present: {others}")
        print(f"  INFO: Consider removing old firmware files to keep the repo clean.")

    return best_path, best_ver_str


def read_changelog(changelog_path: Path, max_chars: int = CHANGELOG_MAX_CHARS) -> str:
    """
    Read and return the first section of a CHANGELOG.md file.
    Returns empty string if file doesn't exist.
    Truncates to max_chars to keep manifest size reasonable.
    """
    if not changelog_path.exists():
        return ""
    try:
        content = changelog_path.read_text(encoding="utf-8").strip()
        if len(content) > max_chars:
            content = content[:max_chars].rsplit("\n", 1)[0] + "…"
        return content
    except Exception:
        return ""


def build_url(file_path: Path) -> str:
    """Build the full raw.githubusercontent.com URL for a given file path."""
    relative = file_path.relative_to(REPO_ROOT).as_posix()
    return f"{REPO_BASE_URL}/{relative}"


def build_entry(file_path: Path, version: str, changelog: str) -> dict:
    """Build a single firmware manifest entry dict."""
    return {
        "version":   version,
        "url":       build_url(file_path),
        "sha256":    sha256_of_file(file_path),
        "size_bytes": file_path.stat().st_size,
        "changelog": changelog,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    manifest = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    errors = []

    # ── Teensy firmware ───────────────────────────────────────────────────────
    teensy_result = find_latest_firmware(TEENSY_DIR, TEENSY_PATTERN)
    if teensy_result:
        teensy_path, teensy_version = teensy_result
        teensy_changelog = read_changelog(TEENSY_CHANGELOG)
        manifest["teensy"] = build_entry(teensy_path, teensy_version, teensy_changelog)
        size = teensy_path.stat().st_size
        sha  = manifest["teensy"]["sha256"]
        print(f"  ✓ Teensy  v{teensy_version}  ({size:,} bytes)  sha256: {sha[:16]}...")
    else:
        errors.append("  ERROR: No Teensy firmware found in firmware/teensy/. "
                      "Expected: trackframe-teensy-v*.hex")

    # ── ESP32 firmware ────────────────────────────────────────────────────────
    esp32_result = find_latest_firmware(ESP32_DIR, ESP32_PATTERN)
    if esp32_result:
        esp32_path, esp32_version = esp32_result
        esp32_changelog = read_changelog(ESP32_CHANGELOG)
        manifest["esp32"] = build_entry(esp32_path, esp32_version, esp32_changelog)
        size = esp32_path.stat().st_size
        sha  = manifest["esp32"]["sha256"]
        print(f"  ✓ ESP32   v{esp32_version}  ({size:,} bytes)  sha256: {sha[:16]}...")
    else:
        errors.append("  ERROR: No ESP32 firmware found in firmware/esp32/. "
                      "Expected: trackframe-esp32-v*.bin")

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        if "teensy" not in manifest and "esp32" not in manifest:
            print("ERROR: No firmware found at all. Aborting.", file=sys.stderr)
            sys.exit(1)

    OUTPUT_FILE.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nfirmware-manifest.json written.")


if __name__ == "__main__":
    main()
