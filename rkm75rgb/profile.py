"""The keyboard's stored 128-byte configuration profile (`cmd 4` / `cmd 132`).

Read, back up, restore and edit what the keyboard keeps for itself: effect,
brightness, speed, report rate, debounce, sleep time, time format and the rest.

Verified on hardware: a field changed with `cmd 4` reads back changed with
`cmd 132`, and after restoring, the profile round-trips byte for byte.

**Not here: a stored per-key colour table.** The official driver has commands
for one (`cmd 6` write, `cmd 134` read) and they exist in the protocol class
shared by this keyboard family, but this firmware never answers `cmd 134` --
probed for ~4 s against a control that replies in 50 ms -- and none of the
neighbouring command ids answer either. On the M75 the colour table is not
implemented, exactly like the TFT/screen commands. The equivalent capability
here is the live RGB frame (`cmd 8`), which is transient.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .protocol import (
    CMD_GET_PROFILE, CMD_SET_PROFILE, LED_MODE_OFF, LED_MODE_SELF_DEFINE,
    LIGHT_EFFECTS, PROFILE_FIELDS, PROFILE_SIZE, PROFILE_SLOTS, REPORT_ID,
    REPORT_SIZE, RESPONSE_DATA_OFFSET,
)
from .transport import Transport


# ------------------------------------------------------------------ packets
def payload(cmd: int, cmd_val: int = 0, data_length: int = 0,
            data: bytes | None = None) -> bytes:
    """The 519-byte feature-report payload used by these commands."""
    p = bytearray(REPORT_SIZE - 1)
    p[0] = cmd
    p[2] = cmd_val & 0xFF
    p[3] = 1
    p[5] = data_length & 0xFF
    p[6] = (data_length >> 8) & 0xFF
    if data is not None:
        if len(data) != data_length:
            raise ValueError(f"data is {len(data)} bytes, expected {data_length}")
        p[7:7 + data_length] = data
    return bytes(p)


def report(cmd: int, cmd_val: int = 0, data_length: int = 0,
           data: bytes | None = None) -> bytes:
    """A full 520-byte feature report (report ID + payload)."""
    return bytes([REPORT_ID]) + payload(cmd, cmd_val, data_length, data)


def _check_slot(slot: int) -> int:
    if not 0 <= slot < PROFILE_SLOTS:
        raise ValueError(f"slot must be 0-{PROFILE_SLOTS - 1}, got {slot}")
    return slot


# ------------------------------------------------------------------- fields
def get_field(profile: bytes, name: str) -> int:
    return profile[_field_offset(name)]


def set_field(profile: bytes, name: str, value: int) -> bytes:
    out = bytearray(profile)
    out[_field_offset(name)] = value & 0xFF
    return bytes(out)


def _field_offset(name: str) -> int:
    key = next((k for k in PROFILE_FIELDS if k.lower() == name.lower()), None)
    if key is None:
        known = ", ".join(sorted(PROFILE_FIELDS))
        raise ValueError(f"unknown field {name!r}. Known fields: {known}")
    return PROFILE_FIELDS[key]


def effect_name(value: int) -> str:
    return LIGHT_EFFECTS[value] if 0 <= value < len(LIGHT_EFFECTS) else f"?{value}"


def effect_index(name: str) -> int:
    for i, effect in enumerate(LIGHT_EFFECTS):
        if effect.lower() == name.lower():
            return i
    raise ValueError(f"unknown effect {name!r}. Known: {', '.join(LIGHT_EFFECTS)}")


# ------------------------------------------------------------------ profile
def read_profile(t: Transport, slot: int = 0) -> bytes:
    slot = _check_slot(slot)
    t.send_report(report(CMD_GET_PROFILE, slot, PROFILE_SIZE))
    resp = t.read_report()
    if resp[1] != CMD_GET_PROFILE:
        raise IOError(f"unexpected reply cmd 0x{resp[1]:02x}")
    return resp[RESPONSE_DATA_OFFSET:RESPONSE_DATA_OFFSET + PROFILE_SIZE]


def write_profile(t: Transport, profile: bytes, slot: int = 0) -> None:
    slot = _check_slot(slot)
    if len(profile) != PROFILE_SIZE:
        raise ValueError(f"expected {PROFILE_SIZE} bytes, got {len(profile)}")
    t.send_report(report(CMD_SET_PROFILE, slot, PROFILE_SIZE, profile))


def describe(profile: bytes) -> list[tuple[str, str]]:
    mode = get_field(profile, "LedMode")
    return [
        ("effect", f"{effect_name(mode)} ({mode})"),
        ("brightness", str(get_field(profile, "LedBrightness"))),
        ("speed", str(get_field(profile, "LedSpeed"))),
        ("colour index", str(get_field(profile, "LedColor"))),
        ("report rate", str(get_field(profile, "ReportRate"))),
        ("debounce", str(get_field(profile, "Debounce"))),
        ("sleep time", str(get_field(profile, "SleepTime"))),
        ("win/mac mode", str(get_field(profile, "WinMacMode"))),
        ("time format", "24h" if get_field(profile, "TimeFormat") else "12h"),
    ]


def backup_path(slot: int) -> Path:
    return Path(f"rk75-profile-slot{slot}.bak")


# ---------------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m rkm75rgb.profile",
        description="Read or edit the keyboard's stored configuration profile.",
        epilog="Any change is preceded by a backup you can --restore.",
    )
    ap.add_argument("--slot", type=int, default=0, help="profile slot (0-3)")
    ap.add_argument("--set", action="append", metavar="FIELD=VALUE", default=[],
                    help="set a profile field, e.g. --set SleepTime=10")
    ap.add_argument("--effect", metavar="NAME",
                    help="switch the stored effect (e.g. SelfDefine, OFF, Rainbow)")
    ap.add_argument("--backup", metavar="PATH", help="save the slot to a file")
    ap.add_argument("--restore", metavar="PATH", help="restore a saved slot")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the automatic backup before changing anything")
    args = ap.parse_args(argv)

    changes: list[tuple[str, int]] = []
    for item in args.set:
        if "=" not in item:
            print(f"error: --set wants FIELD=VALUE, got {item!r}")
            return 2
        field, _, raw = item.partition("=")
        try:
            changes.append((field, int(raw, 0)))
        except ValueError:
            print(f"error: {raw!r} is not a number")
            return 2
    if args.effect:
        try:
            changes.append(("LedMode", effect_index(args.effect)))
        except ValueError as exc:
            print(f"error: {exc}")
            return 2

    t = Transport()
    try:
        if args.restore:
            blob = Path(args.restore).read_bytes()
            if len(blob) != PROFILE_SIZE:
                print(f"error: {args.restore} is {len(blob)} bytes, expected {PROFILE_SIZE}")
                return 2
            write_profile(t, blob, args.slot)
            print(f"restored slot {args.slot} from {args.restore}")
        else:
            current = read_profile(t, args.slot)

            if args.backup:
                Path(args.backup).write_bytes(current)
                print(f"saved slot {args.slot} to {args.backup}")

            if changes:
                if not args.no_backup:
                    path = backup_path(args.slot)
                    if not path.exists():
                        path.write_bytes(current)
                        print(f"backed up the old profile to {path}")

                updated = current
                for field, value in changes:
                    try:
                        before = get_field(updated, field)
                        updated = set_field(updated, field, value)
                    except ValueError as exc:
                        print(f"error: {exc}")
                        return 2
                    shown = f"{before} -> {value}"
                    if field.lower() == "ledmode":
                        shown += f"  ({effect_name(before)} -> {effect_name(value)})"
                    print(f"  {field}: {shown}")

                write_profile(t, updated, args.slot)
                time.sleep(0.2)
                after = read_profile(t, args.slot)
                if after != updated:
                    print("warning: the keyboard did not store what was written")
                    return 1
                print(f"slot {args.slot} updated and verified")
                current = after

            print(f"\nslot {args.slot}")
            for name, value in describe(current):
                print(f"  {name:<14}: {value}")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
