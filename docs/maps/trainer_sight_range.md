# Trainer sight range

The sight range of a field trainer (the number of tiles in front of them in
which they will spot the player and initiate a battle) is **not** stored in
the trainer's party data file under `res/trainers/data/`. It is stored on the
map's object event for that trainer.

## Where it lives

For each map, object events live in `res/field/events/events_<map_name>.json`.
A trainer's object event has `trainer_type` set to a non-zero value (typically
`TRAINER_TYPE_NORMAL`), and its `data` field holds the sight range:

```json
{
    "graphics_id": "OBJ_EVENT_GFX_LASS",
    "movement_type": "MOVEMENT_TYPE_WANDER_AROUND",
    "trainer_type": "TRAINER_TYPE_NORMAL",
    "flag": 0,
    "script": 3324,
    "initial_dir": 3,
    "data": [ 2 ],
    ...
}
```

`data[0]` is the sight range, measured in tiles. The other two slots in `data`
are unused for normal trainers (the JSON commonly lists only the first value;
`tools/json2bin/event.py` pads the array to length 3 when packing).

## How the game uses it

The packed event becomes an `ObjectEvent` (see `include/map_header_data.h`):

```c
typedef struct ObjectEvent {
    u16 localID;
    u16 graphicsID;
    u16 movementType;
    u16 trainerType;
    u16 flag;
    u16 script;
    s16 dir;
    u16 data[3];     // data[0] = sight range for trainers
    s16 movementRangeX;
    s16 movementRangeZ;
    u16 x;
    u16 z;
    fx32 y;
} ObjectEvent;
```

When the player moves, `sub_02067C80` in `src/unk_02067A84.c` performs the
line-of-sight check. It reads `data[0]` via `MapObject_GetDataAt(mapObj, 0)`
and passes it as the maximum tile distance to scan in the trainer's facing
direction:

```c
v2 = MapObject_GetFacingDir(param0);
v1 = MapObject_GetDataAt(param0, 0);   // sight range
v5 = sub_02067DA8(param0, v2, v1, v3, v4, 0);
```

> Do not confuse `data[0]` with the adjacent `movement_range_x` /
> `movement_range_z` fields — those control how far the NPC wanders from its
> spawn tile, not how far it can see.

## Step-by-step: finding the sight range for a specific trainer

1. **Identify the map(s) the trainer stands on.** Map names follow the
   convention `<area>_<sub-area>` (e.g. `hearthome_city_gym_trainer_room_1`).
   `res/field/events/` contains one `events_<map_name>.json` per map.
2. **Open the event file.** Look in the `object_events` array.
3. **Find the trainer.** Trainers have `trainer_type` set to something other
   than `TRAINER_TYPE_NONE`. The `script` value is the trainer's script ID,
   which links the object to the encounter dialogue and battle setup; the
   `graphics_id` (e.g. `OBJ_EVENT_GFX_ACE_TRAINER_M`) tells you which sprite
   they use.
4. **Read `data[0]`.** That number is the sight range in tiles.

To go the other way — from a party data file like
`res/trainers/data/ace_trainer_olivia.json` to the object that places her on
the map — grep `res/field/events/` for the corresponding `script` ID. There
is no back-pointer in the trainer data file itself.

## Worked example: Fantina's gym (Hearthome City)

The Platinum redesign of Fantina's gym splits the trainers across two rooms:

| File                                                            | Trainers | Sight range (`data[0]`) |
| --------------------------------------------------------------- | :------: | :---------------------: |
| `res/field/events/events_hearthome_city_gym_trainer_room_1.json` |    2     |            2            |
| `res/field/events/events_hearthome_city_gym_trainer_room_2.json` |    4     |            2            |

All six gym trainers use a sight range of `2` tiles. Fantina herself, in
`events_hearthome_city_gym_leader_room.json`, is approached via warp rather
than line-of-sight, so her sight range is not relevant.

The Diamond/Pearl version of the gym, kept for reference, uses six rooms
under `events_hearthome_city_dp_gym_trainer_room_1.json` through `_6.json`.

## Changing a sight range

Edit `data[0]` in the relevant `events_<map_name>.json` file and rebuild. The
event JSON is repacked into the ROM's events archive by `tools/json2bin/event.py`
(see `parse_object_event`), which writes the three `data[]` u16s in order.
