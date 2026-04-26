# Trainer Switch AI (Platinum)

How a trainer-controlled Pokémon decides:

1. **whether** to switch out this turn (voluntarily, pre-faint), and
2. **which** party member to send in (both for voluntary switches and
   for replacing a fainted Pokémon).

All citations are to this `stp-pokeplatinum` tree. Function names are as
they appear in the decomp — they are matched to the original ROM, not
guesses.

---

## 0. TL;DR

There are two distinct decisions, each with its own routine:

| Decision | Routine | File:Line |
|---|---|---|
| Should I switch this turn? | `TrainerAI_ShouldSwitch` | `src/battle/trainer_ai/trainer_ai.c:4001` |
| Which mon should come in? | `BattleAI_PostKOSwitchIn` | `src/battle/battle_lib.c:7915` |

`BattleAI_PostKOSwitchIn` is also the routine called when a Pokémon
faints and a replacement must be picked. So the "post-KO switch-in"
algorithm is reused for voluntary switches whenever the heuristic
helpers don't pre-pick a specific slot.

The dispatcher is `TrainerAI_PickCommand` (`trainer_ai.c:4096`):

```c
if ((battleType & BATTLE_TYPE_TRAINER) || Battler_Side(battleSys, battler) == BATTLE_SIDE_PLAYER) {
    if (TrainerAI_ShouldSwitch(battleSys, battleCtx, battler)) {
        // If this is a switch which should use the post-KO switch logic, then do so.
        // If there is no valid battler, pick the first one in party order.
        if (battleCtx->aiSwitchedPartySlot[battler] == 6) {
            if ((i = BattleAI_PostKOSwitchIn(battleSys, battler)) == 6) {
                /* fallback: linear scan to find first alive non-active slot */
            }
            battleCtx->aiSwitchedPartySlot[battler] = i;
        }
        return PLAYER_INPUT_PARTY;
    }
    if (TrainerAI_ShouldUseItem(battleSys, battler)) {
        return PLAYER_INPUT_ITEM;
    }
}
return PLAYER_INPUT_FIGHT;
```

So the per-turn decision is **switch → use item → fight**, in that
priority order.

---

## 1. State variables

Three party-slot fields on `battleCtx` together drive the logic; it's
worth keeping them straight before reading the code.

| Field | Meaning |
|---|---|
| `selectedPartySlot[battler]` | The slot of the Pokémon **currently in battle** for this battler. |
| `aiSwitchedPartySlot[battler]` | The slot the AI has *decided* to switch into this turn. Sentinel value `6` (= `PARTY_SIZE`) means "no decision yet — let `BattleAI_PostKOSwitchIn` choose." |
| `switchedPartySlot[battler]` | The destination slot for an in-flight switch, used by the lower-level battle controller. |

`aiSwitchedPartySlot` is initialized to `6` for every battler at the
start of each turn (`battle_lib.c:2010`). Heuristics that *pre-pick* a
slot write it directly here; heuristics that just trigger a switch
without preference leave it at `6` to defer to the post-KO routine.

---

## 2. Hard "no, don't switch" preconditions

`TrainerAI_ShouldSwitch` (`trainer_ai.c:4001`) opens with:

```c
if ((battleCtx->battleMons[battler].statusVolatile & VOLATILE_CONDITION_TRAPPED)
    || (battleCtx->battleMons[battler].moveEffectsMask & MOVE_EFFECT_INGRAIN)
    || BattleSystem_CountAbility(battleSys, battleCtx, COUNT_ALL_BATTLERS_THEIR_SIDE, battler, ABILITY_SHADOW_TAG)
    || BattleSystem_CountAbility(battleSys, battleCtx, COUNT_ALL_BATTLERS_THEIR_SIDE, battler, ABILITY_ARENA_TRAP)
    || (BattleSystem_CountAbility(battleSys, battleCtx, COUNT_ALL_BATTLERS_EXCEPT_ME, battler, ABILITY_MAGNET_PULL)
        && MON_HAS_TYPE(battler, TYPE_STEEL))) {
    return FALSE;
}
```

In-source comment notes that the AI's reading of these is naïve — it
does not consider its own immunity to ally Magnet Pull, Shadow Tag's
mirror, the Flying-type / Levitate Arena Trap exemption, or Shed Shell.
These are stock Gen 4 quirks.

It then counts alive party members and, if there are none other than
the active ones, returns `FALSE`. Otherwise it walks the heuristic
stack below.

---

## 3. The heuristic stack (the "should I switch?" decision)

The order matters: each heuristic returns `TRUE`/`FALSE` directly, so
the **first** one that fires decides. Several heuristics also write to
`aiSwitchedPartySlot[battler]` to pre-pick the target.

The stack at `trainer_ai.c:4047–4090`:

| # | Heuristic | Pre-picks slot? | Effect |
|---|---|---|---|
| 1 | `AI_PerishSongKO` | leaves at `6` | switch (delegate to post-KO) |
| 2 | `AI_CannotDamageWonderGuard` | yes | switch |
| 3 | `AI_OnlyIneffectiveMoves` | yes | switch |
| 4 | `AI_HasAbsorbAbilityInParty` | yes | switch |
| 5 | `AI_IsAsleepWithNaturalCure` | mixed | switch |
| 6 | `AI_HasSuperEffectiveMove(..., FALSE)` | — | **don't** switch |
| 7 | `AI_IsHeavilyStatBoosted` | — | **don't** switch |
| 8a | `AI_HasPartyMemberWithSuperEffectiveMove(..., 0x8, 2)` | yes | switch |
| 8b | `AI_HasPartyMemberWithSuperEffectiveMove(..., 0x4, 3)` | yes | switch |

Each is described below with its file/line and salient logic.

### 3.1 `AI_PerishSongKO` — `trainer_ai.c:3370`

```c
if ((battleCtx->battleMons[battler].moveEffectsMask & MOVE_EFFECT_PERISH_SONG)
    && battleCtx->battleMons[battler].moveEffectsData.perishSongTurns == 0) {
    battleCtx->aiSwitchedPartySlot[battler] = 6;
    return TRUE;
}
```

If the battler has a Perish Song timer that just hit zero (i.e. would
faint at end of next turn), switch unconditionally. Leaves
`aiSwitchedPartySlot = 6` so post-KO scoring picks the replacement.

### 3.2 `AI_CannotDamageWonderGuard` — `trainer_ai.c:3393`

Singles only (returns FALSE in doubles). If the opponent has Wonder
Guard and **none** of the active mon's moves are super-effective
against it, scan the bench for a party member with a super-effective
move; switch to the first such mon **with `Random() % 3 < 2` per
candidate** (≈66%). Pre-picks the slot.

### 3.3 `AI_OnlyIneffectiveMoves` — `trainer_ai.c:3468`

Two preconditions:

1. Every damaging move (`MOVE_DATA(move).power != 0`) on the active mon
   is `MOVE_STATUS_INEFFECTIVE` against **both** opposing battlers.
2. The active mon has at least 2 attacking moves total
   (`numMoves < 2 → return FALSE`).

If both hold, scan the bench in two passes:

- **Pass 1** (lines 3538–3591): find a party member with an SE move
  vs. either opponent. Per-candidate-per-move `Random() % 3 < 2`
  (≈66%). First match wins; pre-picks slot.
- **Pass 2** (lines 3597–3650): find a party member with at least one
  *neutrally-effective* move vs. either opponent (i.e. not flagged
  ineffective). Per-candidate-per-move `Random() % 2 == 0` (50%).
  Pre-picks slot.

This is one of the more aggressive heuristics: it only triggers when
the active mon is genuinely walled, but once it does it almost
certainly pulls the trigger.

### 3.4 `AI_HasAbsorbAbilityInParty` — `trainer_ai.c:3747`

Triggered by the *last* damaging move that hit this battler. If that
move's type is Fire, Water, or Electric, scan the bench for a party
member whose ability matches the corresponding absorber:

```c
if (moveType == TYPE_FIRE)         checkAbility = ABILITY_FLASH_FIRE;
else if (moveType == TYPE_WATER)   checkAbility = ABILITY_WATER_ABSORB;
else if (moveType == TYPE_ELECTRIC) checkAbility = ABILITY_VOLT_ABSORB;
else return ABILITY_NONE;
```

Then per-candidate `Random() & 1` (50%). Pre-picks slot.

Two short-circuits before the scan:

- If `AI_HasSuperEffectiveMove(..., TRUE)` returns `TRUE` and
  `Random() % 3 != 0` (≈66%), bail. (I.e. don't pivot to an absorb
  ability if you already have super-effective coverage two-thirds of
  the time.)
- If the active mon already has the absorbing ability, bail.

### 3.5 `AI_IsAsleepWithNaturalCure` — `trainer_ai.c:3924`

Three preconditions:

```c
if ((battleCtx->battleMons[battler].status & MON_CONDITION_SLEEP) == FALSE
    || Battler_Ability(battleCtx, battler) != ABILITY_NATURAL_CURE
    || battleCtx->battleMons[battler].curHP < (battleCtx->battleMons[battler].maxHP / 2)) {
    return FALSE;
}
```

Asleep, has Natural Cure, ≥ ½ HP. Then a series of escalating coin
flips, each 50%:

1. If we haven't been hit yet (`moveHit == MOVE_NONE`) → switch
   (post-KO).
2. If the last move that hit was a status move → switch (post-KO).
3. If a party member is **immune** to the last move *and* has an SE
   answer → switch (`AI_HasPartyMemberWithSuperEffectiveMove`,
   `MOVE_STATUS_INEFFECTIVE`, `rand=1`).
4. If a party member **resists** the last move *and* has an SE answer →
   switch (`MOVE_STATUS_NOT_VERY_EFFECTIVE`, `rand=1`).
5. Otherwise random 50% switch (post-KO).

The 1, 2, and 5 paths leave `aiSwitchedPartySlot = 6`; the 3 and 4
paths pre-pick. Importantly, paths 3/4 use `rand = 1` which means the
helper's `Random() % rand == 0` is always true — so paths 3/4 are
deterministic given their pre-conditions.

### 3.6 `AI_HasSuperEffectiveMove(..., FALSE)` — `trainer_ai.c:3667`

Return `FALSE` (= don't switch) if the active mon already has a super-
effective move against either opponent. The `flag = FALSE` mode adds a
per-move `Random() % 10 != 0` gate, so there's a 10% chance per SE
move of failing to "see" it — i.e. the AI may switch even with SE
coverage roughly 1-in-10 times the check fires.

### 3.7 `AI_IsHeavilyStatBoosted` — `trainer_ai.c:3979`

```c
for (stat = BATTLE_STAT_HP; stat < BATTLE_STAT_MAX; stat++) {
    if (battleCtx->battleMons[battler].statBoosts[stat] > 6) {
        numBoosts += battleCtx->battleMons[battler].statBoosts[stat] - 6;
    }
}
return numBoosts >= 4;
```

Sum of positive stat-stage deltas across all stats. ≥ 4 ⇒ don't
switch (preserve the boosts). Note: `> 6` is the in-game internal
encoding for "above default" (6 = 0 stages). HP is included in the
loop but `statBoosts[BATTLE_STAT_HP]` is always 6 in practice so it
contributes nothing.

### 3.8 `AI_HasPartyMemberWithSuperEffectiveMove` — `trainer_ai.c:3834`

Called twice with different parameters:

```c
AI_HasPartyMemberWithSuperEffectiveMove(..., checkEffectiveness=0x8, rand=2);  // 33% per candidate
AI_HasPartyMemberWithSuperEffectiveMove(..., checkEffectiveness=0x4, rand=3);  // 25% per candidate
```

`0x8` is `MOVE_STATUS_INEFFECTIVE` — so the first call asks: "is there
a party member who is **immune** to the last move that hit me, and
who also has an SE counter-move?" `0x4` is
`MOVE_STATUS_NOT_VERY_EFFECTIVE` — same question with "resists" instead
of "immune."

The per-candidate `Random() % rand == 0` rolls produce ≈33% and ≈25%
respectively. First candidate to roll a `0` wins; pre-picks slot.

The two calls are stacked so a "perfect" pivot (immunity + SE) is
preferred to a "good" pivot (resistance + SE), which is preferred to
no pivot at all.

---

## 4. Picking which mon: `BattleAI_PostKOSwitchIn`

`battle_lib.c:7915`. Two-stage scoring routine. Used by
`TrainerAI_PickCommand` after a faint, **and** as the fallback when
`TrainerAI_ShouldSwitch` triggered with `aiSwitchedPartySlot` left at
`6`.

### 4.1 Setup

```c
slot1 = battler;
if ((battleType & BATTLE_TYPE_TAG) || (battleType & BATTLE_TYPE_2vs2)) {
    slot2 = slot1;
} else {
    slot2 = BattleSystem_Partner(battleSys, battler);
}

defender = BattleSystem_RandomOpponent(battleSys, battleCtx, battler);
```

`BattleSystem_RandomOpponent` (`battle_lib.c:4169`):

- In doubles, picks one of the two opposing battlers with
  `BattleSystem_RandNext(battleSys) & 1`. If the pick is fainted,
  swaps to the other.
- In singles, returns `attacker ^ 1` (the opposite-side battler).

So in singles this is deterministic; in doubles there is one RNG call
that decides which opponent the candidates are scored against.

### 4.2 Stage 1 — type matchup score + SE-move filter

```c
// Stage 1: Loop through all the party slots and find the one with the most favorable
// offensive type-matchup against the chosen defender which also has a super-effective
// move against that defender. Choose the Pokemon with the highest such score, breaking
// ties by party-order. If no such Pokemon exists, proceed to Stage 2.
//
// Mono-type Pokemon are regarded as being dual-type of the same type.
while (battlersDisregarded != 0x3F) {
    maxScore = 0;
    picked = 6;

    for (i = 0; i < partySize; i++) {
        /* validity checks: alive, has species, not the in-battle slot,
           not already disregarded, not already chosen by partner */
        if (valid) {
            score  = BattleSystem_TypeMatchupMultiplier(monType1, defenderType1, defenderType2);
            score += BattleSystem_TypeMatchupMultiplier(monType2, defenderType1, defenderType2);

            if (maxScore < score) {
                maxScore = score;
                picked = i;
            }
        } else {
            battlersDisregarded |= FlagIndex(i);
        }
    }

    if (picked != 6) {
        /* check the picked mon's four moves; if any has MOVE_STATUS_SUPER_EFFECTIVE
           via BattleSystem_CalcEffectiveness, return picked. */
        if (i == LEARNED_MOVES_MAX) {
            battlersDisregarded |= FlagIndex(picked); // no SE move; try next-best
        } else {
            return picked;
        }
    } else {
        battlersDisregarded = 0x3F;
        break;
    }
}
```

Important properties:

- **`score` is the candidate's *offensive* matchup against the
  defender.** Both of the candidate's types are run through the chart
  (mono-type → both passes use the same type, doubling-counting on
  purpose per the in-source comment), and the multipliers are
  *summed*. Single-type SE: `20 + 20 = 40`. Dual-type SE × 2: each
  type's `BattleSystem_TypeMatchupMultiplier` already returns the
  product across both defender types (40 in the SE×SE case — see
  §5), so the sum can hit 80+.

  This is the **opposite** sense of the Gen 3 (Emerald/FireRed)
  algorithm, which scored the candidate as a *defender* and (in the
  in-source comment) flagged it as a probable bug. Platinum fixed it.

- **`maxScore < score`** is strict, so on a tie the **earliest** party
  slot keeps the position.

- **Iteration is over the full party** (`0..partySize`), not split by
  flank. Multi-battles in Gen 4 don't slice the party the way
  Gen 3 multi-battles did.

- **The SE-move filter** uses `BattleSystem_CalcEffectiveness`
  (different from `BattleSystem_ApplyTypeChart`), which accounts for
  the candidate's ability and the defender's ability/item/types.
  This means abilities like Levitate / Wonder Guard on either side are
  considered.

- **The outer `while`** retries with the loser disregarded. The
  *highest-scoring* candidate wins **iff** it has at least one SE move.
  If not, it's marked invalid and the loop re-runs to find the
  next-highest. This continues until either some candidate clears both
  bars, or no candidate scores at all.

### 4.3 Stage 2 — raw damage fallback

If Stage 1 exhausts the party with no winner:

```c
maxScore = 0;
picked = 6;

for (i = 0; i < partySize; i++) {
    /* validity checks */
    for (j = 0; j < LEARNED_MOVES_MAX; j++) {
        move = Pokemon_GetValue(mon, MON_DATA_MOVE1 + j, NULL);
        moveType = Move_CalcVariableType(battleSys, battleCtx, mon, move);

        if (move && MOVE_DATA(move).power != 1) {
            score = BattleSystem_CalcMoveDamage(battleSys, battleCtx, move,
                sideConditions, fieldConditions, 0, 0, battler, defender, 1);

            moveStatusFlags = 0;
            score = BattleSystem_ApplyTypeChart(battleSys, battleCtx, move,
                moveType, battler, defender, score, &moveStatusFlags);

            if (moveStatusFlags & MOVE_STATUS_IMMUNE) {
                score = 0;
            }
        }

        if (maxScore < score) {
            maxScore = score;
            picked = i;
        }
    }
}

return picked;
```

Notes:

- Iteration is mon-major, move-minor: every alive eligible candidate
  has all four of its moves scored. The single highest-damage
  `(mon, move)` pair wins.
- `gBattleMoves[move].power != 1` skips the Gen-3-onward sentinel
  power-1 (variable-power moves like Magnitude/Low Kick that would
  break a static damage calc).
- `MOVE_STATUS_IMMUNE` zeroes the score, so type immunities are
  respected even though the calc otherwise produces a number.
- Tie-break is again strict `<` ⇒ earliest slot wins on a tie.
- **Caveat:** `BattleSystem_CalcMoveDamage(..., battler, defender, 1)`
  passes `battler` (= the AI's currently-active, just-fainted Pokémon)
  as the attacker — so the damage is computed using the **outgoing
  mon's stats with the candidate's move**, not the candidate's stats.
  This is the same long-standing quirk Emerald has; Platinum did not
  fix it, only its Stage 1 sister.

If Stage 2 also finds no candidate (`picked == 6`), the caller in
`TrainerAI_PickCommand` (`trainer_ai.c:4112`) does a final linear
"first alive non-active" scan and uses that.

---

## 5. Type chart helper: `BattleSystem_TypeMatchupMultiplier`

`battle_lib.c:3004`:

```c
int BattleSystem_TypeMatchupMultiplier(u8 attackingType, u8 defendingType1, u8 defendingType2)
{
    int i = 0;
    int mul = 40;

    while (sTypeMatchupMultipliers[i][0] != 0xFF) {
        if (sTypeMatchupMultipliers[i][0] == attackingType) {
            if (sTypeMatchupMultipliers[i][1] == defendingType1) {
                mul = mul * sTypeMatchupMultipliers[i][2] / 10;
            }
            if (sTypeMatchupMultipliers[i][1] == defendingType2
                && defendingType1 != defendingType2) {
                mul = mul * sTypeMatchupMultipliers[i][2] / 10;
            }
        }
        i++;
    }
    return mul;
}
```

- Starts at **`mul = 40`** (= "1×" in this routine's units), not 10
  like the Gen 3 helper. So the values it returns are 40 × the actual
  multiplier:
  - 1×  →  40
  - 2×  →  80
  - 0.5× → 20
  - 0×  → 0
- Each chart row that matches `(attackingType, defType1)` or
  `(attackingType, defType2 ≠ defType1)` multiplies by the row's
  multiplier (`5`, `20`, etc., per `include/constants/battle.h:146`)
  divided by 10. So an SE row contributes ×2; an NVE row contributes
  ×0.5; a NO_EFFECT row would zero `mul` (note: NO_EFFECT entries are
  *not* in `sTypeMatchupMultipliers` — this routine only handles the
  basic-effectiveness chart, not the immunity/Foresight machinery,
  which is why it can't return 0 from chart entries alone).

This routine is called *twice* per candidate in Stage 1 (once with
`monType1` as attacker, once with `monType2`) and the results
**summed**. For a mono-type SE candidate vs. mono-type defender,
that's `80 + 80 = 160` — well past the `u8` range of `score`. See §7
for the bug.

The full type chart is at `battle_lib.c:2394` (`sTypeMatchupMultipliers`).
Constants are `TYPE_MULTI_NOT_VERY_EFF = 5` and
`TYPE_MULTI_SUPER_EFF = 20` (`include/constants/battle.h:146`).

---

## 6. Where the lead Pokémon comes from

`BattleAI_PostKOSwitchIn` is *not* used to pick the trainer's
**lead** at battle start. The lead is whoever is in slot 0 of the
trainer's party data (the conventional Gen 4 setup), with
`selectedPartySlot[battler]` populated during battle initialization
before any AI runs. There is no "best matchup" lead selection — same
as Gen 3.

---

## 7. Known bug: `score` overflow in `BattleAI_PostKOSwitchIn`

`battle_lib.c:7925`:

```c
u8 score, maxScore; // BUG: Post-KO Switch-In AI Scoring Overflow (see docs/bugs_and_glitches.md)
```

`score` is `u8`. In Stage 1 the summed type multipliers can reach 160
or more (mono-type vs. mono-type with both passes hitting an SE
matchup). In Stage 2, `score` holds raw damage from
`BattleSystem_CalcMoveDamage` — also frequently > 255. Either case
silently truncates to 8 bits. A documented stock-Platinum bug — see
`docs/bugs_and_glitches.md` for the standard fix (widen to `u32`).

This means in practice:

- Stage 1's "highest score wins" is unreliable when multiple candidates
  are SE — comparison is on the low byte of (often-) 8-bit-wrapped
  values. Lowest-slot tiebreak still applies because of the strict
  `<`, but the "winner" can be a candidate with a worse real matchup
  whose 8-bit-wrapped score happens to land higher.
- Stage 2 is even more affected because realistic damage values are
  routinely above 255.

If you're studying behavior with a build that defines the fix macro,
both stages compute as intended.

---

## 8. RNG inventory

The switch path uses RNG only at well-defined points:

| Site | File:Line | Purpose |
|---|---|---|
| `AI_CannotDamageWonderGuard` | `:3446` | per-candidate `% 3 < 2` |
| `AI_OnlyIneffectiveMoves` (SE pass) | `:3566, :3584` | per-candidate-per-move `% 3 < 2` |
| `AI_OnlyIneffectiveMoves` (neutral pass) | `:3625, :3643` | per-candidate-per-move `% 2` |
| `AI_HasSuperEffectiveMove(..., FALSE)` | `:3695, :3722` | per-SE-move `% 10` |
| `AI_HasAbsorbAbilityInParty` short-circuit | `:3758` | `% 3` |
| `AI_HasAbsorbAbilityInParty` candidate pick | `:3813` | `& 1` (50%) |
| `AI_HasPartyMemberWithSuperEffectiveMove` | `:3903` | per-candidate `% rand` |
| `AI_IsAsleepWithNaturalCure` | `:3935, :3942, :3960` | three `& 1` rolls |
| `BattleSystem_RandomOpponent` | `battle_lib.c:4179` | doubles target pick |

`BattleAI_PostKOSwitchIn` itself is **deterministic** — the only RNG
in the picking phase is the doubles target pick, which then drives a
deterministic scoring loop. In singles, give the same battle state and
you get the same answer.

---

## 9. AI flag gating: there is none (for switching)

Platinum has the standard Gen 4 AI flag set
(`AI_FLAG_BASIC`, `AI_FLAG_RISKY`, etc.), but they gate **move
scoring** in the larger AI elsewhere in `trainer_ai.c`, not the switch
decision. Every trainer with `BATTLE_TYPE_TRAINER` runs the same
`TrainerAI_ShouldSwitch` → `BattleAI_PostKOSwitchIn` pipeline. There
is no "dumb" or "smart" switch path keyed off the trainer class.

The only side-checked condition is at the top of
`TrainerAI_PickCommand` (`:4107`): the routine only runs for trainer
battles or for the player side (when delegated, e.g. for an AI
partner).

---

## 10. Summary of the algorithm

When the AI takes a turn for a trainer-controlled battler:

1. If the battler is hard-locked (Trapped, Ingrain, Shadow Tag, Arena
   Trap, Magnet Pull on a Steel-type) or has nobody to switch to,
   skip the switch decision.
2. Otherwise, run heuristics 1–8 in order. The first to fire decides
   whether to switch. Most of them also pre-pick the target slot.
3. If the AI is switching but no slot was pre-picked, run
   `BattleAI_PostKOSwitchIn`:
   - **Stage 1**: pick the highest-offensive-matchup candidate that
     has at least one SE move against the chosen opposing battler. If
     the top scorer lacks an SE move, mark it disregarded and retry.
   - **Stage 2**: if Stage 1 found nobody, pick the
     `(candidate, move)` pair that produces the highest computed
     damage (using the *active* battler's stats — caveat noted above),
     zeroing immune matchups.
4. If both stages return `6`, fall back to "first alive non-active
   slot in party order."

When a Pokémon faints mid-turn, the same `BattleAI_PostKOSwitchIn`
routine is the picker — but the heuristics in §3 are not consulted,
because the question "should I switch?" is settled (the answer is
yes).

---

## 11. Comparison to Gen 3 (FireRed / Emerald)

| | FireRed/Emerald | Platinum |
|---|---|---|
| **Whether to switch** | `ShouldSwitch` heuristic stack | `TrainerAI_ShouldSwitch` heuristic stack — same idea, slightly different ordering, plus `AI_OnlyIneffectiveMoves` (new in Gen 4) |
| **Stage 1 scoring direction** | Defensive (candidate as defender — in-source comment flags as probable bug) | **Offensive** (candidate as attacker — fixed) |
| **Stage 1 base unit** | `mul = 10` (1.0×), values to ~40 | `mul = 40` (1.0×), values to 160+ |
| **Stage 2 attacker stats** | Uses *active* (often-fainted) battler's stats — quirk | Same quirk: still passes `battler` (active) as attacker |
| **`score`/`bestDmg` type** | `u8`, with optional `BUGFIX` macro to widen | `u8`, no BUGFIX macro in source — flagged as known bug |
| **Multi-battle party slicing** | `firstId/lastId` halves the party | Always full party (Gen 4 multi-battles share a party differently) |
| **Tie-break** | First-encountered (lowest slot) | Same |
| **AI flag gating of switch** | None | None |
| **RNG in picker** | Doubles target pick only | Doubles target pick only |
| **Lead selection** | Slot 0 (hardcoded in Emerald, "first alive non-egg" scan in FireRed) | Slot 0 (from trainer party data) |

So the *structure* is recognizably Gen 3, with two real upgrades —
fixing the defensive→offensive scoring bug, and adding
`AI_OnlyIneffectiveMoves` — and one not-fixed bug
(the `u8` score truncation) that's promoted from a silent issue to a
documented one in `docs/bugs_and_glitches.md`.
