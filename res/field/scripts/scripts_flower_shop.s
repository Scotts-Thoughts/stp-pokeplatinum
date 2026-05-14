#include "macros/scrcmd.inc"
#include "res/text/bank/flower_shop.h"

    .data

    ScriptEntry _000E
    ScriptEntry _006E
    ScriptEntry _00A9
    ScriptEntry _ClearBerryFlag
    ScriptEntryEnd

_000E:
    PlayFanfare SEQ_SE_CONFIRM
    LockAll
    FacePlayer
    GoToIfSet 0xAAA, _0059
    Message 0
    GetStpFloaromaBerry 0x8008
    GoToIfEq 0x8008, 1, _BerryCheri
    GoToIfEq 0x8008, 2, _BerryChesto
    GoToIfEq 0x8008, 3, _BerryPecha
    GoToIfEq 0x8008, 4, _BerryRawst
    GoToIfEq 0x8008, 5, _BerryAspear
    GetRandom 0x8004, 5
    AddVar 0x8004, 149
    GoTo _GiveBerry

_BerryCheri:
    SetVar 0x8004, 149
    GoTo _GiveBerry

_BerryChesto:
    SetVar 0x8004, 150
    GoTo _GiveBerry

_BerryPecha:
    SetVar 0x8004, 151
    GoTo _GiveBerry

_BerryRawst:
    SetVar 0x8004, 152
    GoTo _GiveBerry

_BerryAspear:
    SetVar 0x8004, 153

_GiveBerry:
    SetVar 0x8005, 1
    ScrCmd_07D 0x8004, 0x8005, 0x800C
    GoToIfEq 0x800C, 0, _0064
    SetFlag 0xAAA
    CallCommonScript 0x7E0
    CloseMessage
    ReleaseAll
    End

_0059:
    Message 1
    WaitABXPadPress
    CloseMessage
    ReleaseAll
    End

_0064:
    CallCommonScript 0x7E1
    CloseMessage
    ReleaseAll
    End

_006E:
    PlayFanfare SEQ_SE_CONFIRM
    LockAll
    FacePlayer
    GoToIfSet 128, _009E
    Message 2
    SetVar 0x8004, 0x1C0
    SetVar 0x8005, 1
    SetFlag 128
    CallCommonScript 0x7E0
    CloseMessage
    ReleaseAll
    End

_009E:
    Message 3
    WaitABXPadPress
    CloseMessage
    ReleaseAll
    End

_00A9:
    PlayFanfare SEQ_SE_CONFIRM
    LockAll
    FacePlayer
    ShowAccessoryShop
    ReleaseAll
    End

_ClearBerryFlag:
    ClearFlag 0xAAA
    End

    .byte 0
