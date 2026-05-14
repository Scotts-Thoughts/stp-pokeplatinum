#include "macros/scrcmd.inc"
#include "res/text/bank/pastoria_city_southwest_house.h"

    .data

    ScriptEntry _000A
    ScriptEntry _006A
    ScriptEntry _ClearBerryFlag
    ScriptEntryEnd

_000A:
    PlayFanfare SEQ_SE_CONFIRM
    LockAll
    FacePlayer
    GoToIfSet 0xAA3, _0055
    Message 0
    GetStpPastoriaBerry 0x8008
    GoToIfEq 0x8008, 0, _PastoriaRandom
    SetVar 0x8004, 0x8008
    AddVar 0x8004, 183
    GoTo _PastoriaGive

_PastoriaRandom:
    GetRandom 0x8004, 17
    AddVar 0x8004, 184

_PastoriaGive:
    SetVar 0x8005, 1
    ScrCmd_07D 0x8004, 0x8005, 0x800C
    GoToIfEq 0x800C, 0, _0060
    SetFlag 0xAA3
    CallCommonScript 0x7E0
    CloseMessage
    ReleaseAll
    End

_0055:
    Message 1
    WaitABXPadPress
    CloseMessage
    ReleaseAll
    End

_0060:
    CallCommonScript 0x7E1
    CloseMessage
    ReleaseAll
    End

_006A:
    PlayFanfare SEQ_SE_CONFIRM
    LockAll
    FacePlayer
    Message 2
    WaitABXPadPress
    CloseMessage
    ReleaseAll
    End

_ClearBerryFlag:
    ClearFlag 0xAA3
    End

    .byte 0
    .byte 0
    .byte 0
