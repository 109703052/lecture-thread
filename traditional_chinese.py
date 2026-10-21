"""Traditional Chinese display normalization, independent of factual correction."""
import re
from functools import lru_cache

# Keep explicitly marked code and URLs byte-for-byte; only prose is normalized.
PROTECTED = re.compile(r'(```[\s\S]*?```|`[^`\n]+`|https?://[^\s<>]+)')


@lru_cache(maxsize=1)
def converter():
    from opencc import OpenCC
    # Taiwan character forms, without substituting regional vocabulary (s2twp).
    return OpenCC('s2tw')


def traditional(text):
    parts = PROTECTED.split(text)
    return ''.join(part if i % 2 else converter().convert(part)
                   for i, part in enumerate(parts))


def normalize_transcript(transcript, changes):
    """Normalize a derived transcript in place, retaining raw originals in the audit."""
    by_id = {row['segment_id']: row for row in changes}
    for i, row in enumerate(transcript):
        before = row['text']
        after = traditional(before)
        if before != after:
            row['text'] = after
            if i not in by_id:
                change = dict(segment_id=i, original=before, corrected=after,
                              status='script-normalized', reason='簡體轉繁體（臺灣字形）；不更動原意與時間。',
                              audio_verified=False)
                changes.append(change)
                by_id[i] = change
            by_id[i]['corrected'] = after
            by_id[i]['script_normalization'] = 'OpenCC s2tw'
        if row.get('review_note'):
            row['review_note'] = traditional(row['review_note'])
    for change in changes:
        for field in ('corrected', 'reason', 'basis', 'review_note'):
            if isinstance(change.get(field), str):
                change[field] = traditional(change[field])
    return transcript
