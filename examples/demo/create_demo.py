"""Build the original public demo with stdlib only; writes into ignored output/."""
from array import array
import math
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from build_reader import build
from course_config import load_course


def create_demo():
    course = load_course(ROOT / 'courses/demo.json')
    # The example can only populate its generated directory, never private courses.
    expected = (ROOT / 'output/demo').resolve()
    if course.web_root != expected or course.id != 'lecturethread-demo':
        raise ValueError('Demo manifest must target output/demo with id lecturethread-demo')
    source = Path(__file__).resolve().parent
    course.course_dir.mkdir(parents=True, exist_ok=True)
    for relative in ['authored_notes.json', 'transcript.json', 'slide_evidence.json',
                     'slides/stack.svg', 'slides/queue.svg', 'slides/stack-annotated.svg']:
        target = course.course_dir / relative
        content = (source / relative).read_bytes()
        if target.exists() and target.read_bytes() != content:
            raise ValueError(f'Demo source changed locally; preserving {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(content)
    corrected = course.course_dir / 'transcript.corrected.json'
    if not corrected.exists():
        corrected.write_bytes((source / 'transcript.json').read_bytes())
    course.media.parent.mkdir(parents=True, exist_ok=True)
    if not course.media.exists():
        rate = 22050
        samples = array('h')
        for i in range(36 * rate):
            t = i / rate
            pulse = t % 2
            amplitude = .12 * math.sin(math.pi * pulse / .3) ** 2 if pulse < .3 else 0
            frequency = [330, 440, 550][min(int(t // 12), 2)]
            samples.append(round(32767 * amplitude * math.sin(2 * math.pi * frequency * t)))
        if sys.byteorder != 'little':
            samples.byteswap()
        with wave.open(str(course.media), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(rate)
            audio.writeframes(samples.tobytes())
    build(course)
    print('Demo uses synthetic cue tones, not spoken narration or a real lecture.')
    print('Start: .venv/Scripts/python.exe serve_reader.py --course courses/demo.json --port 8767')
    return course


if __name__ == '__main__':
    create_demo()
