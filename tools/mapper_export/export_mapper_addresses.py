#!/usr/bin/env python3
"""Export per-build RAM addresses to the PokeAByte ST/gen4 platinum_ne mapper.

Run as the final step of every ROM build. It:

  1. Reads POKEPLATINUM_PATCH_VERSION from include/global/pm_version.h.
  2. Parses main.nef.xMAP (CW linker memory map).
  3. Resolves each entry in tools/mapper_export/symbols.json into an absolute
     RAM address.
  4. Merges the resulting record into:
       * tools/mapper_export/patch_versions.json  (committed history)
       * <POKEABYTE_MAPPER_DIR>/patch_versions.json  (live mapper sibling)
     Refuses to silently rewrite an existing version's entry if any address
     changed -- forces a deliberate POKEPLATINUM_PATCH_VERSION bump.
  5. Rewrites the auto-generated PATCH_VERSIONS const block inside
     <POKEABYTE_MAPPER_DIR>/pokemon_platinum_ne.js between sentinel comments.

POKEABYTE_MAPPER_DIR defaults to
  C:/Users/scott/AppData/Roaming/PokeAByte/Mappers/ST/gen4
Override with the env var of the same name.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_POKEABYTE_DIR = Path(
    os.environ.get(
        "POKEABYTE_MAPPER_DIR",
        r"C:/Users/scott/AppData/Roaming/PokeAByte/Mappers/ST/gen4",
    )
)
MAPPER_JS_NAME = "pokemon_platinum_ne.js"
PATCH_VERSIONS_NAME = "patch_versions.json"

SENTINEL_BEGIN = "// === BEGIN PATCH_VERSIONS (auto-generated; do not edit) ==="
SENTINEL_END = "// === END PATCH_VERSIONS ==="


def parse_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise TypeError(f"expected int or str, got {type(value).__name__}")


def read_patch_version(pm_version_h: Path) -> int:
    text = pm_version_h.read_text(encoding="utf-8")
    match = re.search(r"#define\s+POKEPLATINUM_PATCH_VERSION\s+(\d+)", text)
    if not match:
        raise SystemExit(
            f"POKEPLATINUM_PATCH_VERSION not found in {pm_version_h}"
        )
    return int(match.group(1))


_XMAP_LINE = re.compile(
    r"^\s+([0-9A-Fa-f]{6,8})\s+([0-9A-Fa-f]+)\s+(\.\S+)\s+(\S.*?)\s*\(([^)]+)\)\s*$"
)


def parse_xmap(xmap_path: Path) -> dict[str, int]:
    """Return {symbol_name: address} for every symbol in main.nef.xMAP.

    CW's memory map lines look like:
        '  020E4C3C 00000001 .rodata gGameVersion\\t(src_game_version.c.o)'
    Section-name rows (where the 'symbol' equals the section like '.bss') are
    skipped. Zero-size duplicate rows are kept only if no sized row exists.
    """
    symbols: dict[str, int] = {}
    with xmap_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _XMAP_LINE.match(line)
            if not m:
                continue
            addr_hex, size_hex, _section, name, _obj = m.groups()
            name = name.strip()
            if not name or name.startswith("."):
                continue
            addr = int(addr_hex, 16)
            size = int(size_hex, 16)
            if size == 0:
                symbols.setdefault(name, addr)
            else:
                symbols[name] = addr
    return symbols


def resolve_lookup(name: str, spec: dict, symbols: dict[str, int]) -> int:
    if "address" in spec:
        return parse_int(spec["address"])
    if "symbol" in spec:
        sym = spec["symbol"]
        if sym not in symbols:
            raise SystemExit(
                f"Symbol '{sym}' (lookup '{name}') not found in xMAP. "
                f"Edit tools/mapper_export/symbols.json."
            )
        offset = parse_int(spec.get("offset", 0))
        return symbols[sym] + offset
    raise SystemExit(
        f"Lookup '{name}' must have either 'symbol' or 'address' key."
    )


def hex32(n: int) -> str:
    return f"0x{n & 0xFFFFFFFF:08X}"


def load_existing_patch_versions(path: Path) -> dict:
    if not path.exists():
        return {
            "patch_magic": "0x504C5450",
            "by_version": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def addresses_match(a: dict, b: dict) -> bool:
    return (
        a.get("anchor_addr") == b.get("anchor_addr")
        and a.get("lookups") == b.get("lookups")
        and a.get("base_offsets") == b.get("base_offsets")
    )


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def rewrite_js_const(js_path: Path, patch_versions: dict) -> None:
    if not js_path.exists():
        print(
            f"warning: mapper JS not found at {js_path}; skipping const-block rewrite",
            file=sys.stderr,
        )
        return
    original = js_path.read_text(encoding="utf-8")
    block = (
        SENTINEL_BEGIN
        + "\n"
        + "const PATCH_VERSIONS = "
        + json.dumps(patch_versions, indent=2)
        + ";\n"
        + f"const PATCH_MAGIC = {patch_versions['patch_magic']};\n"
        + SENTINEL_END
    )
    if SENTINEL_BEGIN in original and SENTINEL_END in original:
        pattern = re.compile(
            re.escape(SENTINEL_BEGIN) + r"[\s\S]*?" + re.escape(SENTINEL_END)
        )
        new_text = pattern.sub(lambda _m: block, original, count=1)
    else:
        # First-time insert: prepend after the leading // @ts-ignore preamble.
        new_text = block + "\n" + original
    if new_text != original:
        js_path.write_text(new_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Path to the pokeplatinum disassembly root (default: auto-detect).",
    )
    parser.add_argument(
        "--xmap",
        type=Path,
        default=None,
        help="Path to main.nef.xMAP (default: <repo>/build/main.nef.xMAP, "
             "falling back to <repo>/main.nef.xMAP).",
    )
    parser.add_argument(
        "--pokeabyte-dir",
        type=Path,
        default=DEFAULT_POKEABYTE_DIR,
        help="Path to PokeAByte ST/gen4 mapper folder (default: env or hardcoded).",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Don't touch the PokeAByte mapper folder; only update the in-repo copy.",
    )
    parser.add_argument(
        "--stamp",
        type=Path,
        default=None,
        help="Write an empty marker file at this path on success (for build-system tracking).",
    )
    parser.add_argument(
        "--legacy-version",
        type=int,
        default=None,
        help=(
            "Tag this build as a legacy patch (pre-gPatchVersion) with the "
            "given version number. The xMAP must NOT contain gPatchVersion; "
            "the resulting entry has anchor_addr=null and the mapper "
            "identifies it by validating both lookups dereference into the "
            "main-RAM heap range."
        ),
    )
    args = parser.parse_args()

    repo = args.repo_root
    if args.xmap is not None:
        xmap = args.xmap
    else:
        build_xmap = repo / "build" / "main.nef.xMAP"
        repo_xmap = repo / "main.nef.xMAP"
        xmap = build_xmap if build_xmap.exists() else repo_xmap
    pm_version_h = repo / "include" / "global" / "pm_version.h"
    symbols_json = repo / "tools" / "mapper_export" / "symbols.json"
    local_versions = repo / "tools" / "mapper_export" / PATCH_VERSIONS_NAME

    for p in (xmap, pm_version_h, symbols_json):
        if not p.exists():
            print(f"error: required input not found: {p}", file=sys.stderr)
            return 2

    symbols = parse_xmap(xmap)
    config = json.loads(symbols_json.read_text(encoding="utf-8"))

    anchor_symbol = config.get("anchor_symbol", "gPatchVersion")
    anchor_present = anchor_symbol in symbols

    if args.legacy_version is not None:
        if anchor_present:
            print(
                f"error: --legacy-version was passed but '{anchor_symbol}' "
                f"exists in this xMAP. Legacy mode is only for historical "
                f"builds that predate the anchor; remove --legacy-version or "
                f"check out an earlier commit.",
                file=sys.stderr,
            )
            return 2
        version = args.legacy_version
        anchor_addr = None
    else:
        if not anchor_present:
            print(
                f"error: anchor symbol '{anchor_symbol}' not found in xMAP. "
                f"Did you add gPatchVersion to src/game_version.c and "
                f"rebuild? For pre-anchor historical builds, pass "
                f"--legacy-version N instead.",
                file=sys.stderr,
            )
            return 2
        version = read_patch_version(pm_version_h)
        anchor_addr = symbols[anchor_symbol]

    lookups_raw = config.get("lookups", {})
    lookups = {}
    for key, spec in lookups_raw.items():
        if key.startswith("_"):
            continue
        lookups[key] = hex32(resolve_lookup(key, spec, symbols))

    base_offsets = {}
    for key, value in config.get("base_offsets", {}).items():
        if key.startswith("_"):
            continue
        base_offsets[key] = parse_int(value)

    entry = {
        "anchor_addr": hex32(anchor_addr) if anchor_addr is not None else None,
        "lookups": lookups,
        "base_offsets": base_offsets,
    }

    patch_versions = load_existing_patch_versions(local_versions)
    by_version = patch_versions.setdefault("by_version", {})
    key = str(version)
    if key in by_version and not addresses_match(by_version[key], entry):
        print(
            f"error: patch_versions.json already has an entry for version "
            f"{version} with different addresses. Bump "
            f"POKEPLATINUM_PATCH_VERSION in include/global/pm_version.h "
            f"before rebuilding, or delete the stale entry intentionally.",
            file=sys.stderr,
        )
        print("  existing:", json.dumps(by_version[key], indent=2), file=sys.stderr)
        print("  new:     ", json.dumps(entry, indent=2), file=sys.stderr)
        return 3
    by_version[key] = entry

    patch_versions.setdefault("patch_magic", "0x504C5450")

    write_json(local_versions, patch_versions)

    if not args.skip_live:
        live_versions = args.pokeabyte_dir / PATCH_VERSIONS_NAME
        live_js = args.pokeabyte_dir / MAPPER_JS_NAME
        if not args.pokeabyte_dir.exists():
            print(
                f"warning: pokeabyte dir does not exist; skipping live sync: "
                f"{args.pokeabyte_dir}",
                file=sys.stderr,
            )
        else:
            write_json(live_versions, patch_versions)
            rewrite_js_const(live_js, patch_versions)

    if args.stamp is not None:
        args.stamp.parent.mkdir(parents=True, exist_ok=True)
        args.stamp.write_text("", encoding="utf-8")

    if entry["anchor_addr"] is None:
        print(
            f"exported LEGACY mapper addresses for patch version {version} "
            f"(no anchor; {len(entry['lookups'])} lookups; mapper will "
            f"identify by heap-range validation)"
        )
    else:
        print(
            f"exported mapper addresses for patch version {version} "
            f"(anchor {entry['anchor_addr']}, "
            f"{len(entry['lookups'])} lookups)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
