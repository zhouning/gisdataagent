/* Bulk adapter to installed, unmodified EPA SWMM 5.2.4 internal arrays.
 * Native units are feet / cfs; all public adapter quantities are SI.
 * Build against the exact installed headers and library. */
#include <math.h>
#include "headers.h"
extern TNodeStats* NodeStats;
extern double* NodeInflow;
extern double* NodeOutflow;

void aam_state(int count, const int* ids, double* heads, double* flooded,
               double* volumes) {
    for (int k=0;k<count;k++) {
        int i=ids[k];
        heads[k]=(Node[i].invertElev+Node[i].newDepth)*0.3048;
        flooded[k]=NodeStats[i].volFlooded*0.028316846592;
        volumes[k]=Node[i].newVolume*0.028316846592;
    }
}
void aam_forcing(int count, const int* ids, const double* q_cms,
                 const double* surface_heads, const int* wet) {
    for (int k=0;k<count;k++) {
        int i=ids[k];
        Node[i].apiExtInflow=q_cms[k]/0.028316846592;
        if (Node[i].type==JUNCTION) {
            double extra=wet[k] ? surface_heads[k]/0.3048-Node[i].invertElev-Node[i].fullDepth : 0.;
            Node[i].surDepth=fmax(0.,extra);
        }
    }
}
double aam_storage_m3(void) {
    double v=0.;
    for (int i=0;i<Nobjects[NODE];i++)v+=Node[i].newVolume;
    for (int i=0;i<Nobjects[LINK];i++)v+=Link[i].newVolume;
    return v*0.028316846592;
}
double aam_sentinel_flow_cms(int i) {
    return (Node[i].inflow-Node[i].outflow)*0.028316846592;
}
double aam_node_inflow_volume_m3(int i) { return NodeInflow ? NodeInflow[i]*0.028316846592 : NAN; }
double aam_node_outflow_volume_m3(int i) { return NodeOutflow ? NodeOutflow[i]*0.028316846592 : NAN; }
double aam_total_node_outflow_m3(void) {
    double v=0.;
    if (NodeOutflow) for (int i=0;i<Nobjects[NODE];i++) v+=NodeOutflow[i];
    return v*0.028316846592;
}
