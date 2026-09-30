/* Export timestep-integrated SWMM node overflow; no solver code changes. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "swmm5.h"

int main(int argc, char **argv) {
    if (argc != 8) { fprintf(stderr,"usage: export INP RPT OUT VOLUME.bin IDS.txt duration_seconds bin_seconds\n"); return 2; }
    const double duration=atof(argv[6]), interval=atof(argv[7]);
    if (duration<=0 || interval<=0) return 2;
    int err=swmm_open(argv[1],argv[2],argv[3]);
    if (err) { fprintf(stderr,"open error %d\n",err); swmm_close(); return 3; }
    if (swmm_getValue(swmm_FLOWUNITS,0)!=swmm_LPS) { swmm_close(); return 4; }
    int n=swmm_getCount(swmm_NODE), bins=(int)ceil(duration/interval);
    double *vol=calloc((size_t)n*bins,sizeof(double));
    if (!vol) { swmm_close(); return 5; }
    FILE *ids=fopen(argv[5],"w");
    if (!ids) { free(vol);swmm_close();return 6; }
    for(int i=0;i<n;i++) {char name[256];swmm_getName(swmm_NODE,i,name,255);fprintf(ids,"%s\n",name);}
    fclose(ids);
    err=swmm_start(1);
    double previous=0,days=0; long steps=0;
    if (!err) do {
        err=swmm_step(&days); if(err) break;
        double current=days>0?days*86400.0:duration;
        if(current<previous || current>duration+0.01) {err=999;break;}
        double cursor=previous;
        while(cursor<current-1e-9) {
            int bin=(int)floor((cursor+1e-8)/interval);
            if(bin>=bins) break;
            double end=fmin(current,(bin+1)*interval),dt=end-cursor;
            for(int i=0;i<n;i++) {
                double q=swmm_getValue(swmm_NODE_OVERFLOW,i)/1000.0;
                if(q>0) vol[(size_t)bin*n+i]+=q*dt;
            }
            cursor=end;
        }
        previous=current;steps++;
    } while(days>0);
    swmm_end(); swmm_report(); swmm_close();
    if(err) {free(vol);fprintf(stderr,"step error %d\n",err);return 7;}
    FILE *f=fopen(argv[4],"wb"); if(!f){free(vol);return 8;}
    size_t count=(size_t)n*bins;
    if(fwrite(vol,sizeof(double),count,f)!=count){fclose(f);free(vol);return 9;}
    fclose(f);double total=0;for(size_t i=0;i<count;i++)total+=vol[i];free(vol);
    printf("{\"node_count\":%d,\"bin_count\":%d,\"bin_seconds\":%.6f,\"steps\":%ld,\"total_overflow_m3\":%.9f}\n",n,bins,interval,steps,total);
    return 0;
}
