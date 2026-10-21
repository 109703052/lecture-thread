"""Project-local Ollama service; no Windows service or startup registration."""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:11435'
PIDFILE = ROOT / 'data/ollama.pid'
PROCESS_FILE = ROOT / 'data/ollama-process.json'


def owned_process():
    import psutil
    if not PIDFILE.exists():
        raise RuntimeError('Project port is occupied but no project PID record exists; refusing to use or stop an unknown server')
    pid = int(PIDFILE.read_text())
    process = psutil.Process(pid)
    if Path(process.exe()).resolve() != (ROOT/'tools/ollama/ollama.exe').resolve():
        raise RuntimeError('PID belongs to a different program; refusing to stop it')
    if PROCESS_FILE.exists():
        record = json.loads(PROCESS_FILE.read_text(encoding='utf-8'))
        if record['pid'] != pid or record['created_at'] != process.create_time():
            raise RuntimeError('Project Ollama PID was reused; refusing to stop a different process')
    return process


if sys.argv[1:] == ['stop']:
    if PIDFILE.exists():
        import psutil
        try:
            p = owned_process()
            for child in p.children(recursive=True): child.terminate()
            p.terminate()
            p.wait(timeout=15)
        except psutil.NoSuchProcess: pass
        PIDFILE.unlink()
        PROCESS_FILE.unlink(missing_ok=True)
    try:
        urllib.request.urlopen(BASE+'/api/version', timeout=2).close()
    except OSError:
        pass
    else:
        raise RuntimeError('Project port still serves Ollama; shutdown is not confirmed')
    print('Project Ollama stopped')
    raise SystemExit(0)
try:
    urllib.request.urlopen(BASE+'/api/version', timeout=2)
    owned_process()
    print('Project port is already serving Ollama; no new service started')
    raise SystemExit(0)
except OSError: pass
env=os.environ.copy()
env.update(OLLAMA_HOST='127.0.0.1:11435', OLLAMA_MODELS=str(ROOT/'models/ollama'),
           OLLAMA_NO_CLOUD='1', OLLAMA_KEEP_ALIVE='0', OLLAMA_MAX_LOADED_MODELS='1',
           OLLAMA_NUM_PARALLEL='1', USERPROFILE=str(ROOT/'tools/ollama-profile'))
(ROOT/'tools/ollama-profile').mkdir(exist_ok=True)
with (ROOT/'data/ollama.log').open('ab') as log:
    p=subprocess.Popen([str(ROOT/'tools/ollama/ollama.exe'),'serve'],env=env,
        cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
PIDFILE.write_text(str(p.pid))
import psutil
PROCESS_FILE.write_text(json.dumps(dict(pid=p.pid, created_at=psutil.Process(p.pid).create_time())), encoding='utf-8')
for i in range(30):
    try:
        with urllib.request.urlopen(BASE+'/api/version',timeout=2) as r: print(r.read().decode())
        break
    except OSError:
        if p.poll() is not None: raise RuntimeError('Ollama exited; see data/ollama.log')
        time.sleep(1)
else: raise RuntimeError('Ollama did not become ready; see data/ollama.log')
