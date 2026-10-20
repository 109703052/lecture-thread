"""Project-local Ollama service; no Windows service or startup registration."""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:11435'
if sys.argv[1:] == ['stop']:
    pidfile = ROOT / 'data' / 'ollama.pid'
    if pidfile.exists():
        import psutil
        pid = int(pidfile.read_text())
        try:
            p = psutil.Process(pid)
            if Path(p.exe()).resolve() != (ROOT/'tools/ollama/ollama.exe').resolve():
                raise RuntimeError('PID belongs to a different program; refusing to stop it')
            for child in p.children(recursive=True): child.terminate()
            p.terminate()
            p.wait(timeout=15)
        except psutil.NoSuchProcess: pass
        pidfile.unlink()
    print('Project Ollama stopped')
    raise SystemExit(0)
try:
    urllib.request.urlopen(BASE+'/api/version', timeout=2)
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
(ROOT/'data/ollama.pid').write_text(str(p.pid))
for i in range(30):
    try:
        with urllib.request.urlopen(BASE+'/api/version',timeout=2) as r: print(r.read().decode())
        break
    except OSError:
        if p.poll() is not None: raise RuntimeError('Ollama exited; see data/ollama.log')
        time.sleep(1)
else: raise RuntimeError('Ollama did not become ready; see data/ollama.log')
