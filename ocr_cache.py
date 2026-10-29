"""Exact decoded-pixel OCR cache. Never infer equivalence from visual similarity."""
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path

from pipeline_common import atomic_json, digest, read_json

ROOT = Path(__file__).resolve().parent


def engine_signature():
    """Default RapidOCR only: invalidate on code, config, model or runtime changes."""
    package = importlib.util.find_spec('rapidocr_onnxruntime')
    if package is None:
        raise RuntimeError('RapidOCR is required for OCR')
    folder = Path(package.origin).parent
    files = {str(p.relative_to(folder)): digest(p) for p in sorted(folder.rglob('*'))
             if p.is_file() and p.suffix in {'.py', '.onnx', '.yaml', '.yml', '.txt', '.json'}}
    return dict(schema=1, package_files=files,
                versions={name: importlib.metadata.version(name)
                          for name in ('rapidocr-onnxruntime', 'onnxruntime', 'Pillow')},
                adapter=digest(__file__),
                common=digest(ROOT/'vendor/lecture-to-notes/scripts/_common.py'))


def pixel_identity(image):
    pixels = image.convert('RGB')
    return hashlib.sha256(str(pixels.size).encode()+pixels.tobytes()).hexdigest()


class OCRCache:
    def __init__(self, folder, signature):
        self.folder = Path(folder)
        self.signature = signature
        self.hits = self.misses = 0

    def recognize(self, path, recognize, identity=None):
        """identity: pixel_identity of this exact file, when the caller already has it."""
        if identity is None:
            from PIL import Image
            with Image.open(path) as source:
                identity = pixel_identity(source)
        key = hashlib.sha256(json.dumps([self.signature, identity], sort_keys=True).encode()).hexdigest()
        target = self.folder/(key+'.json')
        if target.exists():
            try:
                saved = read_json(target)
                result = saved['result']
                if (saved['key'] == key and saved['result_sha256'] ==
                        hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
                        and len(result) == 4 and result[3] is None):
                    self.hits += 1
                    return tuple(copy.deepcopy(result))
            except (ValueError, KeyError, TypeError):
                pass  # damaged cache is recomputed, never mistaken for evidence
        self.misses += 1
        result = recognize(str(path))
        if result[3] is None:
            # Normalize numpy scalar/array values before persistent serialization.
            result = json.loads(json.dumps(result, default=lambda v: v.tolist()))
            atomic_json(target, dict(key=key, result=result,
                result_sha256=hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()))
        return tuple(copy.deepcopy(result))


def install(module):
    original = module.rapidocr_text_ex
    caches = {}
    signature = None
    def cached(path, engine=None):
        nonlocal signature
        if signature is None:
            signature = engine_signature()
        folder = Path(path).resolve().parent.parent/'ocr-cache'
        cache = caches.setdefault(folder, OCRCache(folder, signature))
        return cache.recognize(path, lambda p: original(p, engine))
    module.rapidocr_text_ex = cached
