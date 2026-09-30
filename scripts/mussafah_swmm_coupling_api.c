/* Narrow bridge compiled against the installed EPA SWMM 5.2.4 headers.
 * No change to the solver; cumulative flooding is integrated by SWMM at
 * every native routing step, not reconstructed from report samples. */
#include <math.h>
#include "headers.h"
extern TNodeStats* NodeStats;

double mussafah_flood_volume_m3(int i) {
    if (!NodeStats || i < 0 || i >= Nobjects[NODE]) return NAN;
    return NodeStats[i].volFlooded * 0.028316846592;
}

double mussafah_storage_m3(void) {
    double v = 0.;
    for (int i=0; i<Nobjects[NODE]; ++i) v += Node[i].newVolume;
    for (int i=0; i<Nobjects[LINK]; ++i) v += Link[i].newVolume;
    return v * 0.028316846592;
}

/* Native node flooding starts at the higher of the surveyed surcharge
 * crest and the wet surface head. Restore the original crest when dry. */
void mussafah_surface_head(int i, double stage_m, double original_surcharge_m,
                          int wet) {
    if (i < 0 || i >= Nobjects[NODE] || Node[i].type != JUNCTION) return;
    double extra = wet ? stage_m / 0.3048 - Node[i].invertElev - Node[i].fullDepth : 0.;
    Node[i].surDepth = fmax(original_surcharge_m / 0.3048, extra);
}
