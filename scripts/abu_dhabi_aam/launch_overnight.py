"""Start an independent session so the computation survives this chat turn."""
from pathlib import Path
import datetime,json,os,subprocess,sys
HERE=Path(__file__).resolve().parent
statuspath=HERE/'overnight_status.json'
if statuspath.exists():
    status=json.loads(statuspath.read_text());pid=status.get('supervisor_pid')
    if pid:
        try:os.kill(pid,0)
        except ProcessLookupError:pass
        else:
            print(json.dumps({'already_running':True,**status},ensure_ascii=False,indent=2));sys.exit(0)
env=os.environ.copy();env['PYTHONUNBUFFERED']='1'
with (HERE/'supervisor.log').open('ab',buffering=0) as log:
    p=subprocess.Popen([sys.executable,str(HERE/'overnight_supervisor.py')],cwd=HERE,
        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
receipt={'supervisor_pid':p.pid,'launched_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    'detached_session':True,'status_file':str(statuspath),'log':str(HERE/'supervisor.log')}
(HERE/'overnight_launch_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False,indent=2),flush=True)
