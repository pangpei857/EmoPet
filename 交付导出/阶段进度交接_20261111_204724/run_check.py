from pathlib import Path
from datetime import datetime
import json,os,subprocess,sys,time
base=Path(__file__).resolve().parent
label=sys.argv[1]
command=sys.argv[2:]
env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen';env['PYTHONIOENCODING']='utf-8'
started=time.time()
try:
    result=subprocess.run(command,cwd=base/'source_snapshot',env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    code=result.returncode;stdout=result.stdout;stderr=result.stderr
except subprocess.TimeoutExpired as error:
    code=124;stdout=str(error.stdout or '');stderr=str(error.stderr or '')+'\nTIMEOUT after 180 seconds'
(base/'verification'/f'{label}.stdout.txt').write_text(stdout,encoding='utf-8')
(base/'verification'/f'{label}.stderr.txt').write_text(stderr,encoding='utf-8')
data={'label':label,'command':command,'cwd':str(base/'source_snapshot'),'offscreen':True,'exit_code':code,'elapsed_seconds':round(time.time()-started,3)}
(base/'verification'/f'{label}.result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(data,ensure_ascii=False));print(stdout[-1600:]);print(stderr[-2400:])
sys.exit(code)
