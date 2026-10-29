"""Run upstream Python scripts with project-local dependencies and caches."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT / 'vendor' / 'lecture-to-notes'
env = os.environ.copy()
for name, path in {
    'HF_HOME': ROOT / 'models' / 'huggingface',
    'XDG_CACHE_HOME': ROOT / 'models' / 'cache',
    'TORCH_HOME': ROOT / 'models' / 'torch',
    'OLLAMA_MODELS': ROOT / 'models' / 'ollama',
    'UV_CACHE_DIR': ROOT / 'tools' / 'uv-cache',
    'UV_PYTHON_INSTALL_DIR': ROOT / 'tools' / 'python',
    'UV_PYTHON_BIN_DIR': ROOT / 'tools' / 'python-bin',
    'TEMP': ROOT / 'data' / 'tmp',
    'TMP': ROOT / 'data' / 'tmp',
}.items():
    path.mkdir(parents=True, exist_ok=True)
    env[name] = str(path)
env['PYTHONUTF8'] = '1'
env['PYTHONIOENCODING'] = 'utf-8'
env['OLLAMA_HOST'] = '127.0.0.1:11435'
env['OLLAMA_URL'] = 'http://127.0.0.1:11435/api/generate'
env['OLLAMA_NO_CLOUD'] = '1'
site = ROOT / '.venv' / 'Lib' / 'site-packages'
paths = [ROOT / '.venv' / 'Scripts', site / 'pypandoc' / 'files']
paths += list((site / 'nvidia').glob('*/bin'))
env['PATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + env.get('PATH', '')
args = sys.argv[1:]
if not args:
    print('Usage: run.cmd scripts/route_inputs.py <material-folder>')
    raise SystemExit(0)
if args[0].startswith('scripts/') or args[0].startswith('scripts\\'):
    args[0] = str(REPO / args[0])
if Path(args[0]).name in {'quick_ocr.py', 'vlm_signals.py', 'ground_slides.py', 'export_web.py'}:
    args = [str(ROOT / 'profile_stage.py'), *args]
raise SystemExit(subprocess.call([sys.executable, *args], env=env, cwd=REPO))
