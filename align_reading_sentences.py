"""Draft and apply sentence-level source maps for an authored reading layer.

`draft` splits each reading paragraph into sentences and proposes, by monotonic
text-overlap alignment, which contiguous corrected originals each sentence
condenses. The proposal is written to a separate file with a review report; it
is a starting point for human review, not evidence of a correct mapping.
`apply` validates a reviewed draft and stores it in transcript.reading.json
after backing up the previous file. Paragraph text and originals never change.
"""
import argparse, datetime, functools, hashlib, json, re, shutil
from pathlib import Path

from course_config import load_course
from reading_layer import validate_sentences

TERMINAL = '。！？!?'
CLOSERS = '」』）)”’'


def split_sentences(text):
    parts, start, i = [], 0, 0
    while i < len(text):
        if text[i] in TERMINAL:
            i += 1
            while i < len(text) and (text[i] in TERMINAL or text[i] in CLOSERS or text[i].isspace()):
                i += 1
            parts.append(text[start:i]); start = i
        else:
            i += 1
    if start < len(text):
        if parts and not text[start:].strip():
            parts[-1] += text[start:]
        else:
            parts.append(text[start:])
    return parts


def tokens(text):
    text = text.lower()
    words = re.findall(r'[a-z0-9]+', text)
    han = re.sub(r'[^一-鿿]', '', text)
    return [*words, *(han[i:i+2] for i in range(len(han)-1)), *han]


# Discourse fillers that carry no content; a trailing original made only of these
# ("那所以在這邊的話") usually introduces the next sentence rather than ending this one.
FILLER = set('那所以在這邊的話呢就是我們說個一它他這樣子好嗯啊了也然後要')


def content(text):
    return [t for t in tokens(text) if t != 'ok' and not all(c in FILLER for c in t)]


def shift_lead_ins(sentences, originals, ranges):
    ranges = [list(r) for r in ranges]
    for j in range(len(ranges) - 1):
        while (ranges[j][1] > ranges[j][0] and ranges[j+1][0] == ranges[j][1] + 1
               and not overlap(content(sentences[j]), content(originals[ranges[j][1]]))):
            ranges[j][1] -= 1; ranges[j+1][0] -= 1
    return ranges


def overlap(a, b):
    counts = {}
    for t in b:
        counts[t] = counts.get(t, 0) + 1
    hit = 0
    for t in a:
        if counts.get(t):
            counts[t] -= 1; hit += 1
    return hit


def align(sentences, originals):
    """Best monotonic cover: sentence j takes originals [a, b]; the next starts at b or b+1."""
    k, n = len(sentences), len(originals)
    stoks = [tokens(s) for s in sentences]
    otoks = [tokens(o) for o in originals]

    @functools.lru_cache(maxsize=None)
    def score(j, a, b):
        r = [t for o in otoks[a:b+1] for t in o]
        if not stoks[j] and not r:
            return 0.0
        return 2 * overlap(stoks[j], r) / (len(stoks[j]) + len(r) or 1)

    NEG = float('-inf')
    best = [[NEG] * n for _ in range(k)]   # best[j][b]: sentences 0..j placed, j ends at b
    back = [[None] * n for _ in range(k)]
    for b in range(n):
        best[0][b] = score(0, 0, b)
    for j in range(1, k):
        for b in range(n):
            for prev in range(b + 1):
                if best[j-1][prev] == NEG:
                    continue
                for a in {prev, prev + 1}:
                    if a > b:
                        continue
                    value = best[j-1][prev] + score(j, a, b)
                    if value > best[j][b]:
                        best[j][b], back[j][b] = value, (prev, a)
    ranges, b = [], n - 1
    for j in range(k - 1, -1, -1):
        if j == 0:
            ranges.append((0, b)); break
        prev, a = back[j][b]
        ranges.append((a, b)); b = prev
    ranges.reverse()
    return [(a, b, score(j, a, b)) for j, (a, b) in enumerate(ranges)]


def draft(course, output):
    path = course.course_dir / 'transcript.reading.json'
    doc = json.loads(path.read_text(encoding='utf-8'))
    report, result = [], []
    for index, p in enumerate(doc['paragraphs']):
        ids, texts = p['source_ids'], split_sentences(p['text'])
        if len(texts) > len(ids):
            # More sentences than originals: keep whole-paragraph mapping for review.
            texts = [p['text']]
        rows = align(texts, p['originals'])
        ranges = shift_lead_ins(texts, p['originals'], [(a, b) for a, b, _ in rows])
        sentences = [dict(text=t, source_ids=list(range(ids[a], ids[b] + 1)), score=round(s, 3))
                     for t, (a, b), (_, _, s) in zip(texts, ranges, rows)]
        result.append(dict(paragraph=index, sentences=sentences))
        report.append(f'## 段 {index}（來源 {ids[0]}–{ids[-1]}）')
        for s in sentences:
            report.append(f'- [{s["score"]:.2f}] {s["text"].strip()}')
            for i in s['source_ids']:
                report.append(f'    {i}: {p["originals"][i - ids[0]]}')
    output = Path(output)
    output.write_text(json.dumps(dict(reading_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                      paragraphs=result), ensure_ascii=False, indent=1), encoding='utf-8')
    output.with_suffix('.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(f'Drafted {sum(len(r["sentences"]) for r in result)} sentences in {len(result)} paragraphs -> {output}')


def apply(course, draft_path, label):
    path = course.course_dir / 'transcript.reading.json'
    plan = json.loads(Path(draft_path).read_text(encoding='utf-8'))
    if plan['reading_sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError('transcript.reading.json changed since the draft; draft again')
    doc = json.loads(path.read_text(encoding='utf-8'))
    if len(plan['paragraphs']) != len(doc['paragraphs']):
        raise ValueError('Draft paragraph count does not match the reading layer')
    for p, row in zip(doc['paragraphs'], plan['paragraphs']):
        sentences = [dict(text=s['text'], source_ids=s['source_ids']) for s in row['sentences']]
        validate_sentences(sentences, p['source_ids'], p['text'])
        p['sentences'] = sentences
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = course.course_dir / 'backups' / f'{label}-{stamp}'
    backup.mkdir(parents=True)
    shutil.copy2(path, backup / path.name)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    print(f'Applied sentence maps to {len(doc["paragraphs"])} paragraphs; backup in {backup}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['draft', 'apply'])
    parser.add_argument('--course', type=Path, required=True)
    parser.add_argument('--draft', type=Path, required=True, help='Draft JSON to write (draft) or read (apply)')
    parser.add_argument('--label', default='reading-sentences')
    args = parser.parse_args()
    course = load_course(args.course)
    try:
        draft(course, args.draft) if args.command == 'draft' else apply(course, args.draft, args.label)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
