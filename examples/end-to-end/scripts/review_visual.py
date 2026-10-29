"""Prepare a human review packet for a `lecture.cmd visual` output.

Usage (project root):
  .venv/Scripts/python.exe examples/end-to-end/scripts/review_visual.py --job output/jobs/<id> [--visual DIR]

Reads alignment.json, differences.json, region-ocr.json and change-scan.json
(the real detector outputs) and writes <job>/visual-human-review/:
  review.md              runs, scan events, difference events with OCR clues
  runs.png               first frame of every candidate page run
  diff-XX.png            before/after full-resolution crops of each difference event
  decisions.template.json  every run and difference event, decision "pending"

It never reads expected_events.json and never decides anything. A person
copies the template to decisions.json, looks at the images, and fills in each
decision; build_evidence.py refuses pending or stale decisions.
"""
import argparse
from pathlib import Path
import sys

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT))
from pipeline_common import atomic_json, digest, read_json  # noqa: E402

DIFF_DECISIONS = ('annotation_add', 'annotation_erase', 'reveal', 'content_change', 'noise')
RUN_DECISIONS = ('confirmed', 'corrected', 'split', 'noise')


def stamp(value):
    value = float(value)
    return f'{int(value)//60:02}:{value%60:05.2f}'


def thumbnail(path, width):
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert('RGB')
        return image.resize((width, round(image.height*width/image.width)))


def label(image, text):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, 22), fill=(255, 255, 255))
    draw.text((6, 4), text, fill=(0, 0, 0))
    return image


def sheet(tiles, columns, out):
    from PIL import Image
    w, h = tiles[0].width, max(t.height for t in tiles)
    rows = -(-len(tiles)//columns)
    canvas = Image.new('RGB', (columns*w + (columns+1)*8, rows*h + (rows+1)*8), (200, 200, 200))
    for i, tile in enumerate(tiles):
        canvas.paste(tile, (8 + (i % columns)*(w+8), 8 + (i//columns)*(h+8)))
    canvas.save(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--visual', type=Path, help='lecture.cmd visual --out folder (default <job>/visual-review)')
    args = parser.parse_args(argv)
    job = args.job.resolve()
    visual = (args.visual or job/'visual-review').resolve()
    status = read_json(visual/'status.json')
    if status.get('state') != 'review_required':
        raise SystemExit(f'Visual workflow not finished: {visual/"status.json"}')
    alignment = read_json(visual/'alignment.json')
    differences = read_json(visual/'differences.json')
    ocr = read_json(visual/'region-ocr.json') if (visual/'region-ocr.json').exists() else None
    scan = read_json(visual/'change-scan.json')
    out = job/'visual-human-review'
    out.mkdir(exist_ok=True)
    by_time = {row['time']: row for row in alignment['observations']}

    tiles = []
    for i, run in enumerate(alignment['intervals']):
        row = by_time[run['start']]
        tiles.append(label(thumbnail(row.get('comparison_image', row['image']), 320),
                           f'R{i+1:02} {stamp(run["start"])} {run["page_id"] or run["status"]}'))
    sheet(tiles, 4, out/'runs.png')
    ocr_events = ocr['events'] if ocr else [None]*len(differences['events'])
    for i, (event, recognized) in enumerate(zip(differences['events'], ocr_events)):
        tiles = []
        if recognized:
            for side in ('before', 'after'):
                for j, region in enumerate(recognized[side]['regions']):
                    tiles.append(label(thumbnail(region['image'], 300), f'{side} {stamp(recognized[side]["time"])} #{j+1}'))
        else:
            tiles = [label(thumbnail(event['before_compared'], 480), 'before'),
                     label(thumbnail(event['after_compared'], 480), 'after')]
        sheet(tiles, 2 if not recognized else max(1, len(recognized['before']['regions'])), out/f'diff-{i+1:02}.png')

    lines = ['# 視覺核對包', '',
             f'來源：`{visual}`（`lecture.cmd visual` 實際輸出）。本檔只整理偵測結果，不含任何判定。', '',
             f'- 1 fps 換頁探針：{scan["probes"]} 格，{len(scan["events"])} 個面積變化事件（門檻 2.5%）',
             f'- 觀察點：{len(alignment["observations"])}；不確定（ambiguous／unmatched）：'
             f'{sum(r["status"] != "candidate" for r in alignment["observations"])}',
             f'- 局部差異事件：{len(differences["events"])}', '',
             '## 頁面候選區間（runs.png）', '', '| Run | 起 | 末次觀察 | 狀態 | 候選頁 | 觀察數 |', '|---|---|---|---|---|---|']
    for i, run in enumerate(alignment['intervals']):
        lines.append(f'| R{i+1:02} | {stamp(run["start"])} | {stamp(run["last_observed"])} | {run["status"]} | '
                     f'{run["page_id"]} | {run["observations"]} |')
    lines += ['', '## 1 fps 換頁探針事件', '']
    lines += [f'- {e["before"]}→{e["after"]} s，變化面積 {e["changed_fraction"]:.3f}' for e in scan['events']]
    lines += ['', '## 局部差異事件（diff-XX.png：上排 before、下排 after 裁切）', '']
    for i, (event, recognized) in enumerate(zip(differences['events'], ocr_events)):
        lines.append(f'### D{i+1:02}｜{event["page_id"]}｜{stamp(event["before_time"])} → {stamp(event["after_time"])}')
        lines.append(f'- 變化像素 {event["changed_pixels"]}，{len(event["boxes_in_video_coordinates"])} 個區域（960 寬座標）')
        if recognized:
            for side in ('before', 'after'):
                texts = [r['text'].replace('\n', ' ') or '∅' for r in recognized[side]['regions']]
                lines.append(f'- OCR {side}（線索，不是判定）：' + '｜'.join(texts))
        lines.append('')
    (out/'review.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    template = dict(
        schema=1, alignment_sha256=digest(visual/'alignment.json'), differences_sha256=digest(visual/'differences.json'),
        region_ocr_sha256=digest(visual/'region-ocr.json') if ocr else None,
        reviewer='', reviewed_at='', method='',
        allowed=dict(runs=list(RUN_DECISIONS), differences=list(DIFF_DECISIONS)),
        runs=[dict(id=f'R{i+1:02}', start=r['start'], last_observed=r['last_observed'], status=r['status'],
                   candidate_page=r['page_id'], decision='pending', page_id=r['page_id'], note='')
              for i, r in enumerate(alignment['intervals'])],
        differences=[dict(id=f'D{i+1:02}', page_id=e['page_id'], before_time=e['before_time'], after_time=e['after_time'],
                          decision='pending', meaning='', note='')
                     for i, e in enumerate(differences['events'])],
        missed=[])
    atomic_json(out/'decisions.template.json', template)
    print(f'Review packet: {out}\n  {len(alignment["intervals"])} runs, {len(differences["events"])} difference events; '
          f'copy decisions.template.json to decisions.json and fill every decision')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
