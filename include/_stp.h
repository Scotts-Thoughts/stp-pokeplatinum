#ifndef POKEPLATINUM__STP_H
#define POKEPLATINUM__STP_H

struct StpVars {
    u32 starterSpecies;
    u32 greatMarshShard;
    u32 floaromaBerry;
    u32 berryMaster;
    u32 pastoriaBerry;
};

extern struct StpVars stpVars;

#define stpStarterSpecies  (stpVars.starterSpecies)
#define stpGreatMarshShard (stpVars.greatMarshShard)
#define stpFloaromaBerry   (stpVars.floaromaBerry)
#define stpBerryMaster     (stpVars.berryMaster)
#define stpPastoriaBerry   (stpVars.pastoriaBerry)

extern u32 stpStarterPosition;

#endif // POKEPLATINUM__STP_H
