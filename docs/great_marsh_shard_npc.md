# Great Marsh Lookout — Daily Shard NPC

A reference for the NPC at the top of the Pastoria Observatory (the Great
Marsh lookout) who gives the player one random shard per day. This document
describes the script that drives the giveaway and lists the knobs you'd
touch to change its behavior.

## Files

| Purpose | File |
|---|---|
| Script source (the giveaway logic) | `res/field/scripts/scripts_great_marsh_6.s` |
| Object/sign placement on this map | `res/field/events/events_great_marsh_6.json` |
| Text bank for the NPC's lines | `res/text/great_marsh_6.gmm` |
| Script-command opcodes referenced below | `asm/macros/scrcmd.inc` |
| Shard item IDs / GBA constants | `res/items/pl_item_data.csv`, `include/constants/gba/items.h` |

The script file is named `great_marsh_6` because internally the Pastoria
Observatory rooftop is the 6th map in the Great Marsh map group (warps in
`events_great_marsh_6.json` connect back to `MAP_HEADER_PASTORIA_CITY_OBSERVATORY_GATE_1F`).

## Behavior at a glance

1. Player talks to the NPC.
2. If the player has already received a shard today (event flag `0xAB4` is
   set), play the "come back tomorrow" message and exit.
3. Otherwise roll a uniform random number in `[0, 4)`.
4. Pick a shard ID from a fixed table based on that roll:
   - `0 → 72` (Red Shard)
   - `1 → 73` (Blue Shard)
   - `2 → 74` (Yellow Shard)
   - `3 → 75` (Green Shard)
5. Try to add 1 of that shard to the bag. If it fits, set flag `0xAB4` and
   play the "received" common subscript. If the bag is full, play the "no
   room" common subscript and **do not** set the flag (so the player can
   try again later after making space).

Each shard has equal probability (¼). The roll does not depend on player
progress, day of week, location, or held items.

## The script — `scripts_great_marsh_6.s`

The interaction handler is the second `ScriptEntry` in the file
(`scripts_great_marsh_6.s:7`), label `_000A`:

```asm
_000A:
    PlayFanfare SEQ_SE_CONFIRM
    LockAll
    FacePlayer
    GoToIfSet 0xAB4, _00BC       ; daily-gate: already given today?
    Message 0                    ; "Want a shard?" intro line
    GetRandom 0x8004, 4          ; roll in [0, 4)
    SetVar 0x8008, 0x8004
    GoToIfEq 0x8008, 0, _005B    ; -> Red
    GoToIfEq 0x8008, 1, _0069    ; -> Blue
    GoToIfEq 0x8008, 2, _0077    ; -> Yellow
    GoTo _0085                   ; default -> Green

_005B: SetVar 0x8004, 72  GoTo _0093    ; ITEM_RED_SHARD
_0069: SetVar 0x8004, 73  GoTo _0093    ; ITEM_BLUE_SHARD
_0077: SetVar 0x8004, 74  GoTo _0093    ; ITEM_YELLOW_SHARD
_0085: SetVar 0x8004, 75  GoTo _0093    ; ITEM_GREEN_SHARD

_0093:
    SetVar 0x8005, 1             ; quantity = 1
    ScrCmd_07D 0x8004, 0x8005, 0x800C   ; "give item": 0x800C := success?
    GoToIfEq 0x800C, 0, _00C7    ; 0 = bag full -> "no room" branch
    SetFlag 0xAB4                ; arm the daily lockout
    CallCommonScript 0x7E0       ; "you received <item>!"
    CloseMessage
    ReleaseAll
    End

_00BC:                           ; already-given-today branch
    Message 1
    WaitABXPadPress
    CloseMessage
    ReleaseAll
    End

_00C7:                           ; bag-full branch
    CallCommonScript 0x7E1       ; "make some room and come back"
    CloseMessage
    ReleaseAll
    End
```

### Key opcodes

These are defined in `asm/macros/scrcmd.inc`:

- `GetRandom destVar, upperBound` (opcode 439, line 2403) — writes a
  uniformly random integer in `[0, upperBound)` to `destVar`. The script
  uses `upperBound = 4`, so the result is one of `{0, 1, 2, 3}`.
- `ScrCmd_07D itemVar, qtyVar, resultVar` (opcode 125, line 739) — the
  "give item to bag" command. Reads the item ID and quantity *from
  variables* (not literals), writes `1` to `resultVar` if the item was
  added, `0` if the bag couldn't hold it.
- `SetFlag flagID` / `GoToIfSet flagID, label` — event-flag set/check.

### Working variables and flags

| Var/Flag | Role in this script |
|---|---|
| `0x8004` | Reused: first holds the random roll, then is overwritten with the chosen item ID for `ScrCmd_07D`. |
| `0x8005` | Quantity (always 1). |
| `0x8008` | Copy of the roll used by the `GoToIfEq` switch. |
| `0x800C` | Return code from `ScrCmd_07D`: 1 = added, 0 = bag full. |
| Flag `0xAB4` | Daily "already received" lock. Set after a successful give; checked at the top of the script. |

Variables `0x8000`–`0x800F` are the standard script scratch register bank;
they are not persisted and may be clobbered by any other script.

### How "refreshes every day" works

The script itself does **not** clear flag `0xAB4`. That happens through the
game's daily-event reset path — the same one that respawns hidden items,
berry growth, etc. The script just sets the flag; the daily tick is what
unsets it. Don't add a clear of `0xAB4` inside this script; that would
either break the daily gating or fight the global reset.

If you want to verify the reset wiring, the daily clearing hooks live
around `FieldSystem_ClearDailyHiddenItemFlags` in `src/script_manager.c`
and the per-day tick path through `src/unk_020559DC.c:124`. Flag `0xAB4` is
in the general event-flag space (not the hidden-item flag space), so its
reset is handled by the broader daily-event machinery rather than that
specific clearing function.

## Common modifications

### Change the set of items, or weight them

The fixed `0 → Red`, `1 → Blue`, `2 → Yellow`, `3 → Green` mapping is
encoded in the four small landing labels `_005B / _0069 / _0077 / _0085`.
To swap in different items, edit the `SetVar 0x8004, <item ID>` line in
each branch. Item IDs are the row order in `res/items/pl_item_data.csv`
(see the table at the top of this doc for the shard IDs).

To weight the rolls (e.g. make Green rarer), increase the `GetRandom`
upper bound and add more branches that point to the common items. For
example, `GetRandom 0x8004, 10` with 3 buckets each for Red/Blue/Yellow
and 1 bucket for Green gives Green a 10% rate. Each new `GoToIfEq` adds
one bucket.

### Change the give quantity

`SetVar 0x8005, 1` at `_0093` is the count. Bumping it to `5` would hand
out 5 of whichever shard rolled. `ScrCmd_07D` will still return 0 if the
full stack doesn't fit, which preserves the bag-full handling.

### Change the cadence (twice a day, once a week, no limit)

- **No limit:** delete the `GoToIfSet 0xAB4, _00BC` line and the
  `SetFlag 0xAB4` line. The `_00BC` block becomes dead code; you can
  leave it or remove it.
- **Once per week / longer cadence:** the script only knows about event
  flags, which the daily tick resets. For coarser cadences, store the
  last-given day in a save var via `system_vars.c` and gate on that
  instead. This is a bigger change — `0xAB4` alone cannot express it.
- **Tie to time of day:** call `GetTimeOfDay 0x800B` (opcode 438,
  `scrcmd.inc:2393`) and branch on the result before the random roll.

### Move the NPC, or add more NPCs

The object that runs `_000A` is declared in
`res/field/events/events_great_marsh_6.json`. The script entry table in
`scripts_great_marsh_6.s:6-8` is what the `script:` field in that JSON
indexes into (1-based, top-down). If you copy this NPC to another map,
copy `_000A` (plus its labels) into that map's script file, add a
matching `ScriptEntry` line, and point a new object_event at the new
index. **Don't share `_000A` across maps by name** — script labels are
file-local.

If multiple NPCs in the world should share one "you already got a shard
today" lockout, they must all check and set the same flag. If they
should be independent, give each one its own flag and make sure that
flag is in the range cleared by the daily reset.

### Change the text the NPC says

`Message 0`, `Message 1` index into the bank
`res/text/great_marsh_6.gmm`. Message 0 is the intro / pre-give line and
Message 1 is the "come back tomorrow" line. The common-script calls
`0x7E0` / `0x7E1` use the standard "received item" / "no room" lines and
are shared with every other item-giving NPC in the game; don't override
them locally.

## Cross-references

- Shard item definitions: `res/items/pl_item_data.csv:74-77`,
  `include/constants/gba/items.h:52-55`.
- Other shard-handling NPCs (for reference, not part of this feature):
  - Fuego Ironworks Star Piece trader — `res/field/scripts/scripts_fuego_ironworks_building.s` (gives one of *each* shard, not a random pick).
  - Shard exchange shops (Route 212, Snowpoint, Survival Area) use
    `PayShardsCost` in `scripts_common.s:1697`.
- Opcode reference: `asm/macros/scrcmd.inc`.
