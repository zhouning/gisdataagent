"""Detached local supervisor: run both authorized full cases, then export.
No messages, network access, desktop notifications or data uploads.
"""
from pathlib import Path
import datetime,json,os,subprocess,sys,time,traceback

HERE=Path(__file__).resolve().parent
ANUGA=Path('/Users/zhouning/gisdataagent/external_models/anuga-venv/bin/python')
GIS=Path('/Users/zhouning/gisdataagent/.venv/bin/python')
def now():return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
def dump(obj):
    path=HERE/'overnight_status.json';tmp=path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(path)
def main():
    os.chdir(HERE)
    env=os.environ.copy()
    env.update(OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONUNBUFFERED='1')
    status={'schema':'aam.overnight.v1','status':'starting','supervisor_pid':os.getpid(),
        'started_at':now(),'updated_at':now(),'duration_seconds_per_case':18000,
        'rainfall':'60 mm uniformly over first 3600s, followed by 14400s with no rain',
        'grid_spacing_m':100,'scenarios':{},'known_quality_issue':'600s junction trial failed SWMM continuity; user requested immediate full diagnostic runs on 2026-10-16',
        'export':'copy original .out/.rpt/.sww after both native runs finish; preserve original bytes and quality flags',
        'notification':'local status files only'}
    dump(status)
    logs=[];children={}
    caffeinate_log=(HERE/'caffeinate.log').open('a')
    try:
        prevent_sleep=subprocess.Popen(['/usr/bin/caffeinate','-i','-m','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=caffeinate_log,stderr=subprocess.STDOUT)
        status['caffeinate_pid']=prevent_sleep.pid
    except OSError as exc:status['caffeinate_error']=str(exc)
    for scenario in ['L1','L2']:
        out=HERE/'results'/scenario;out.mkdir(parents=True,exist_ok=True)
        if (out/'run_receipt.json').exists():raise RuntimeError(f'{scenario} already completed; refusing overwrite')
        log=(out/'execution.log').open('ab',buffering=0);logs.append(log)
        command=[str(ANUGA),str(HERE/'run_aam.py'),'--scenario',scenario,'--collection','results','--duration','18000','--step','30','--threads','4']
        child=subprocess.Popen(command,cwd=HERE,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env)
        children[scenario]=child
        status['scenarios'][scenario]={'pid':child.pid,'status':'running','started_at':now(),'command':command,'log':str(out/'execution.log')}
    status['status']='running';dump(status)
    while True:
        pending=False
        for scenario,child in children.items():
            item=status['scenarios'][scenario];returncode=child.poll()
            if returncode is None:pending=True
            else:
                item['returncode']=returncode
                if 'ended_at' not in item:item['ended_at']=now()
                item['status']='solver_finished' if returncode==0 else 'failed'
            progress=HERE/'results'/scenario/'progress.json'
            if progress.exists():
                try:item['progress']=json.loads(progress.read_text())
                except (OSError,ValueError):pass
            receipt=HERE/'results'/scenario/'run_receipt.json'
            if receipt.exists():
                try:item['quality_passed']=json.loads(receipt.read_text())['quality_passed']
                except (OSError,ValueError,KeyError):pass
        status['updated_at']=now();dump(status)
        if not pending:break
        time.sleep(15)
    if all(child.returncode==0 for child in children.values()):
        status['status']='exporting';status['updated_at']=now();dump(status)
        with (HERE/'export.log').open('ab',buffering=0) as log:
            child=subprocess.Popen([str(ANUGA),str(HERE/'package_native_results.py')],cwd=HERE,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            status['export_pid']=child.pid;dump(status)
            status['export_returncode']=child.wait()
        if status['export_returncode']==0:
            status['status']='completed' if all(i.get('quality_passed') for i in status['scenarios'].values()) else 'completed_quality_failed'
            status['native_result_package']=str(HERE/'AAM_L1_L2_原生计算结果_100m_60mm1h_退水4h.zip')
            status['results_directory']=str(HERE/'results')
        else:status['status']='solvers_finished_export_failed'
    else:status['status']='failed';status['reason']='At least one native run stopped; inspect each execution.log; no complete comparison claimed.'
    status['updated_at']=status['ended_at']=now();dump(status)
    for log in logs:log.close()
    print(json.dumps(status,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    try:main()
    except BaseException:
        error={'status':'supervisor_failed','supervisor_pid':os.getpid(),'updated_at':now(),'error':traceback.format_exc()}
        dump(error);raise
