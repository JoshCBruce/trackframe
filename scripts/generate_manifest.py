#!/usr/bin/env python3
"""
generate_manifest.py
TRACKFRAME XL — Race Manifest Generator

Scans the races/ directory for all .tfr files, computes SHA-256 hashes,
and writes a fresh manifest.json to the repo root.

Run automatically by GitHub Actions on every push that modifies races/.
Can also be run locally: python3 scripts/generate_manifest.py

Expected filename format: {YYYY}-{circuit}-{session}.tfr
  e.g. 2025-bahrain-race.tfr
       2025-monaco-qualifying.tfr
       2025-silverstone-sprint.tfr
"""

import json
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).parent.parent
RACES_DIR   = REPO_ROOT / "races"
OUTPUT_FILE = REPO_ROOT / "manifest.json"

REPO_BASE_URL = "https://raw.githubusercontent.com/JoshCBruce/TrackFrame/main"

MANIFEST_VERSION = 2

# Maps lowercase keyword (found anywhere in the circuit part of the filename)
# to the full official circuit name.
CIRCUIT_NAMES = {
    "bahrain":     "Bahrain International Circuit",
    "saudi":       "Jeddah Corniche Circuit",
    "jeddah":      "Jeddah Corniche Circuit",
    "australia":   "Albert Park Circuit",
    "albert":      "Albert Park Circuit",
    "japan":       "Suzuka International Racing Course",
    "suzuka":      "Suzuka International Racing Course",
    "china":       "Shanghai International Circuit",
    "shanghai":    "Shanghai International Circuit",
    "miami":       "Miami International Autodrome",
    "monaco":      "Circuit de Monaco",
    "canada":      "Circuit Gilles Villeneuve",
    "spain":       "Circuit de Barcelona-Catalunya",
    "barcelona":   "Circuit de Barcelona-Catalunya",
    "austria":     "Red Bull Ring",
    "britain":     "Silverstone Circuit",
    "silverstone": "Silverstone Circuit",
    "hungary":     "Hungaroring",
    "hungaroring": "Hungaroring",
    "belgium":     "Circuit de Spa-Francorchamps",
    "spa":         "Circuit de Spa-Francorchamps",
    "netherlands": "Circuit Zandvoort",
    "zandvoort":   "Circuit Zandvoort",
    "italy":       "Autodromo Nazionale Monza",
    "monza":       "Autodromo Nazionale Monza",
    "singapore":   "Marina Bay Street Circuit",
    "marina":      "Marina Bay Street Circuit",
    "usa":         "Circuit of the Americas",
    "cota":        "Circuit of the Americas",
    "austin":      "Circuit of the Americas",
    "mexico":      "Autodromo Hermanos Rodriguez",
    "brazil":      "Autodromo Jose Carlos Pace",
    "interlagos":  "Autodromo Jose Carlos Pace",
    "lasvegas":    "Las Vegas Strip Circuit",
    "vegas":       "Las Vegas Strip Circuit",
    "qatar":       "Lusail International Circuit",
    "lusail":      "Lusail International Circuit",
    "abudhabi":    "Yas Marina Circuit",
    "yas":         "Yas Marina Circuit",
}

VALID_SESSIONS = {"race", "qualifying", "sprint", "sprintqualifying", "practice1",
                  "practice2", "practice3"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def sha256_of_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file, reading in 64 KB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_circuit_name(raw_circuit: str) -> str:
    """
    Given the raw circuit string extracted from the filename (e.g. 'bahrain',
    'abudhabi', 'lasvegas'), return the full official name.
    Falls back to title-cased raw string if no match found.
    """
    lower = raw_circuit.lower().replace("-", "").replace("_", "")
    for keyword, full_name in CIRCUIT_NAMES.items():
        if keyword in lower:
            return full_name
    # Fallback: make it readable at least
    return raw_circuit.replace("-", " ").title()


def parse_filename(filename: str):
    """
    Parse a .tfr filename into (season, circuit_raw, session).
    Expected format: YYYY-{circuit}-{session}.tfr
    The circuit part may contain hyphens (e.g. abu-dhabi, las-vegas).
    Session is always the last hyphen-separated segment before .tfr.
    Returns None if the filename doesn't match the expected format.
    """
    stem = Path(filename).stem  # strip .tfr
    parts = stem.split("-")

    if len(parts) < 3:
        return None

    try:
        season = int(parts[0])
        if season < 1950 or season > 2100:
            return None
    except ValueError:
        return None

    session = parts[-1].lower().replace(" ", "")
    if session not in VALID_SESSIONS:
        # Try combining last two parts (e.g. sprint-qualifying → sprintqualifying)
        combined = (parts[-2] + parts[-1]).lower()
        if combined in VALID_SESSIONS:
            session = combined
            circuit_parts = parts[1:-2]
        else:
            # Unknown session — still include but flag it
            circuit_parts = parts[1:-1]
    else:
        circuit_parts = parts[1:-1]

    circuit_raw = "-".join(circuit_parts)
    return season, circuit_raw, session


def build_race_url(tfr_path: Path) -> str:
    """Build the full raw.githubusercontent.com URL for a given file path."""
    # Make path relative to repo root and use forward slashes
    relative = tfr_path.relative_to(REPO_ROOT).as_posix()
    return f"{REPO_BASE_URL}/{relative}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not RACES_DIR.exists():
        print(f"ERROR: races/ directory not found at {RACES_DIR}", file=sys.stderr)
        sys.exit(1)

    tfr_files = sorted(RACES_DIR.rglob("*.tfr"))

    if not tfr_files:
        print("WARNING: No .tfr files found in races/. Writing empty manifest.")

    races = []
    errors = []

    # Track round numbers per season (incremented only on 'race' sessions)
    round_counter: dict[int, int] = {}
    # Track last round seen per season for non-race sessions
    last_round: dict[int, int] = {}

    for tfr_path in tfr_files:
        filename = tfr_path.name
        parsed = parse_filename(filename)

        if parsed is None:
            errors.append(f"  SKIP (bad filename format): {filename}")
            continue

        season, circuit_raw, session = parsed
        circuit_full = resolve_circuit_name(circuit_raw)

        # Assign round number: race sessions increment the counter;
        # non-race sessions (qualifying, sprint, etc.) share the same round
        # as the race they precede/follow.
        if session == "race":
            round_counter[season] = round_counter.get(season, 0) + 1
            last_round[season] = round_counter[season]
        round_num = last_round.get(season, round_counter.get(season, 1))

        file_size = tfr_path.stat().st_size
        sha256    = sha256_of_file(tfr_path)
        url       = build_race_url(tfr_path)

        races.append({
            "filename":   filename,
            "circuit":    circuit_full,
            "season":     season,
            "round":      round_num,
            "session":    session,
            "size_bytes": file_size,
            "sha256":     sha256,
            "url":        url,
        })

        print(f"  ✓ {filename}  ({file_size:,} bytes)  sha256: {sha256[:16]}...")

    # Load existing manifest to preserve the deprecated list
    deprecated = []
    if OUTPUT_FILE.exists():
        try:
            existing = json.loads(OUTPUT_FILE.read_text())
            deprecated = existing.get("deprecated", [])
        except (json.JSONDecodeError, KeyError):
            pass

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "updated":          datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "race_count":       len(races),
        "races":            races,
        "deprecated":       deprecated,
    }

    OUTPUT_FILE.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\nmanifest.json written — {len(races)} race(s)")

    if errors:
        print("\nWarnings (files skipped):")
        for e in errors:
            print(e)

    if errors and len(races) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
