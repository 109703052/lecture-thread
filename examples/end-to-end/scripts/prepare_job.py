"""Create the example job, its deck registry, and run only the source + ASR stages.

Usage (project root):
  .venv/Scripts/python.exe examples/end-to-end/scripts/prepare_job.py [--materials DIR] [--job-id ID]

`lecture.cmd start` would continue into the legacy OCR/VLM/local-model authoring
stages. This tool reuses the same job format and the real `Worker.source` /
`Worker.transcribe` stages (FFmpeg H.264 copy, faster-whisper large-v3 on CUDA
with the CS glossary) and stops there. The job is marked `codex-direct`, so a
later `lecture.cmd resume` refuses to run the legacy local authoring route.

Re-running with the same job ID verifies the job and skips stages whose
artifacts still match their recorded hashes.
"""
import argparse
from pathlib import Path
import sys

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT))
from lecture_pipeline import PIPELINE_LOCK, Worker, create_job, job_path  # noqa: E402
from pipeline_common import atomic_json, digest, exclusive_lock, read_json  # noqa: E402

DEFAULT_MATERIALS = ROOT/'output/e2e-circular-queue/materials'
DEFAULT_JOB = 'e2e-circular-queue'


def ensure_job(video, job_id, title):
    folder = job_path(job_id)
    if folder.exists():
        config = read_json(folder/'job.json')
        status = read_json(folder/'status.json')
        if config['source_fingerprint']['sha256'] != digest(video):
            raise ValueError(f'{folder} belongs to a different video; choose a new --job-id')
        if digest(folder/'job.json') != status['job_sha256']:
            raise ValueError('job.json changed after creation; choose a new --job-id')
        return folder
    folder = create_job(str(video), job_id, title)
    config = read_json(folder/'job.json')
    # Direct authoring: the legacy worker's preflight refuses this job from now on.
    config.update(authoring_mode='codex-direct',
                  route='examples/end-to-end: source + ASR stages, then lecture.cmd visual and editorial_publish.py')
    atomic_json(folder/'job.json', config)
    status = read_json(folder/'status.json')
    status['job_sha256'] = digest(folder/'job.json')
    atomic_json(folder/'status.json', status)
    return folder


def write_references(materials, target):
    deck = read_json(materials/'deck.json')
    import pymupdf
    with pymupdf.open(materials/'deck.pdf') as doc:
        count = len(doc)
    if count != len(deck['pages']):
        raise ValueError('deck.pdf page count differs from deck.json')
    refs = [dict(deck_id=deck['deck_id'], source=str((materials/'deck.json').resolve()),
                 source_sha256=digest(materials/'deck.json'), render_pdf=str((materials/'deck.pdf').resolve()),
                 render_sha256=digest(materials/'deck.pdf'), slide_count=count)]
    if target.exists() and read_json(target) != refs:
        raise ValueError(f'{target} describes a different deck; regenerate into a new folder')
    atomic_json(target, refs)
    return refs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--materials', type=Path, default=DEFAULT_MATERIALS)
    parser.add_argument('--job-id', default=DEFAULT_JOB)
    parser.add_argument('--title', default='循環佇列：如何分辨空與滿（原創端到端範例）')
    args = parser.parse_args(argv)
    materials = args.materials.resolve()
    video = materials/'lecture.mp4'
    if not video.is_file():
        raise SystemExit(f'Missing {video}; run generate_materials.py first')
    references = write_references(materials, materials.parent/'references.json')
    with exclusive_lock(PIPELINE_LOCK):
        folder = ensure_job(video, args.job_id, args.title)
        worker = Worker(folder)
        worker.stage('source', worker.source)
        worker.stage('transcribe', worker.transcribe)
        status = read_json(folder/'status.json')
        status.update(state='review_required', current_stage='visual (lecture.cmd visual)')
        atomic_json(folder/'status.json', status)
    stages = read_json(folder/'status.json')['stages']
    print(f'Job: {folder}\nReferences: {materials.parent/"references.json"} ({references[0]["slide_count"]} pages)')
    for name in ('source', 'transcribe'):
        print(f'  {name}: {stages[name]["state"]}, {stages[name].get("elapsed_seconds")} s')
    print(f'Raw ASR: {folder/"course/transcript.json"} sha256 {digest(folder/"course/transcript.json")}')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
