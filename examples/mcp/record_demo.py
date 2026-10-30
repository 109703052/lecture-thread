"""Run the MCP demo through a real SDK stdio client and record every request and response.

Usage (project root):
  .venv/Scripts/python.exe examples/mcp/record_demo.py --registry mcp.courses.example.json --check
  .venv/Scripts/python.exe examples/mcp/record_demo.py --registry mcp.courses.example.json --out docs/mcp-demo-record.md
  .venv/Scripts/python.exe examples/mcp/record_demo.py --registry mcp.courses.local.json --circular-queue
      --out data/reports/mcp-circular-queue-record.md

The server is spawned exactly as an AI host would (absolute interpreter, script and
registry). --check asserts the expected facts and writes nothing. The record holds
tool names, arguments and responses only; it fails if any local path leaks into it.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(sys.executable).resolve()

from mcp import ClientSession, StdioServerParameters, stdio_client  # noqa: E402
from importlib.metadata import version  # noqa: E402

DEMO = 'lecturethread-demo'
QUEUE = 'e2e-circular-queue'


class Recorder:
    def __init__(self, session):
        self.session, self.steps = session, []

    async def call(self, title, name, arguments):
        result = await self.session.call_tool(name, arguments)
        body = result.structured_content
        if body is None or json.loads(result.content[0].text) != body:
            raise AssertionError(f'{name}: text and structured content differ')
        self.steps.append(dict(title=title, tool=name, arguments=arguments, is_error=result.is_error, response=body))
        return body, result.is_error


async def demo_steps(rec):
    listing, _ = await rec.call('1. 列出已登錄課程', 'list_courses', {})
    demo = next((c for c in listing['data']['courses'] if c['id'] == DEMO), None)
    assert demo and demo['status'] == 'ok', 'public demo is not registered or not built (run examples/demo/create_demo.py)'
    assert demo['raw_transcript_origin'] == 'scripted'
    revision = demo['revision']
    found, _ = await rec.call('2. 搜尋 queue（校訂稿層）', 'search_course',
                              dict(course_id=DEMO, query='queue', layer='corrected_transcript', expected_revision=revision))
    ids = [r['source_id'] for r in found['data']['results']]
    assert ids == [2, 3], ids
    chinese, _ = await rec.call('2b. 中文搜尋「先進先出」', 'search_course',
                                dict(course_id=DEMO, query='先進先出', expected_revision=revision))
    assert [r['source_id'] for r in chinese['data']['results']] == [2]
    context, _ = await rec.call('3. 取得 source 2 的原句、時間與畫面', 'get_source_context',
                                dict(course_id=DEMO, source_ids=[2], before=1, after=1, expected_revision=revision))
    source = context['data']['sources'][0]
    assert (source['start'], source['end']) == (12, 18)
    assert [o['occurrence_id'] for o in source['occurrences']] == [2]
    occurrences, _ = await rec.call('4. 列出全部投影片出現紀錄', 'get_slide_occurrences',
                                    dict(course_id=DEMO, expected_revision=revision))
    rows = occurrences['data']['occurrences']
    assert [o['occurrence_id'] for o in rows] == [1, 2, 3] and all(o['page_id'] is None for o in rows)
    revisit, _ = await rec.call('4b. 回頁那段的來源（回到 stack 並加註）', 'get_source_context',
                                dict(course_id=DEMO, source_ids=[4], before=0, after=0, expected_revision=revision))
    assert [o['occurrence_id'] for o in revisit['data']['sources'][0]['occurrences']] == [3]
    missing, is_error = await rec.call('5. 錯誤示範：示範課程沒有 editorial notes', 'search_course',
                                       dict(course_id=DEMO, query='stack', layer='editorial_notes'))
    assert is_error and missing['error']['code'] == 'LAYER_UNAVAILABLE'


async def circular_queue_steps(rec):
    listing, _ = await rec.call('Q1. 列出已登錄課程', 'list_courses', {})
    course = next((c for c in listing['data']['courses'] if c['id'] == QUEUE), None)
    assert course and course['status'] == 'ok', 'local circular-queue course is not registered'
    revision = course['revision']
    notes, _ = await rec.call('Q2. 搜尋講義中的「滿」條件', 'search_course',
                              dict(course_id=QUEUE, query='rear + 1', layer='editorial_notes', limit=5,
                                   expected_revision=revision))
    assert notes['data']['results'], 'no note hit'
    ids = notes['data']['results'][0]['source_ids'][:4]
    await rec.call('Q3. 讀原始／校訂來源與畫面', 'get_source_context',
                   dict(course_id=QUEUE, source_ids=ids, before=0, after=0, expected_revision=revision))
    pages, _ = await rec.call('Q4. 同一頁 cq:3 的每次出現（含回頁與逐步出現）', 'get_slide_occurrences',
                              dict(course_id=QUEUE, page_id='cq:3', expected_revision=revision))
    assert len(pages['data']['occurrences']) >= 2


async def run(registry, steps, errlog):
    params = StdioServerParameters(command=str(PYTHON),
                                   args=[str(ROOT / 'lecture_mcp_server.py'), '--registry', str(registry)])
    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            rec = Recorder(session)
            await steps(rec)
    return init, tools, rec.steps


def render(init, tools, steps, label):
    lines = [f'# MCP 展示紀錄：{label}', '',
             '> 由 `examples/mcp/record_demo.py` 以官方 Python MCP SDK 的真實 stdio client 啟動 '
             '`lecture_mcp_server.py` 後實際呼叫產生；以下每個回應都是 server 當次的輸出，未手動改寫。'
             '這不是 AI host 的對話紀錄。', '',
             f'- 產生時間：{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
             f'- SDK：mcp {version("mcp")}（mcp-types {version("mcp-types")}）；Python {sys.version.split()[0]}',
             f'- 協商的協定版本：`{init.protocol_version}`；server：`{init.server_info.name}` {init.server_info.version}',
             f'- tools/list：{", ".join(f"`{t.name}`" for t in tools)}（皆標示 readOnlyHint）', '']
    for step in steps:
        lines += [f'## {step["title"]}', '', f'請求：`{step["tool"]}`', '', '```json',
                  json.dumps(step['arguments'], ensure_ascii=False, indent=1), '```', '',
                  f'回應（isError={str(step["is_error"]).lower()}）：', '', '```json',
                  json.dumps(step['response'], ensure_ascii=False, indent=1), '```', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--circular-queue', action='store_true', help='Run the optional local circular-queue steps')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--check', action='store_true', help='Assert the demo facts and write nothing')
    args = parser.parse_args(argv)
    registry = args.registry if args.registry.is_absolute() else ROOT / args.registry
    steps = circular_queue_steps if args.circular_queue else demo_steps
    init, tools, recorded = asyncio.run(run(registry.resolve(), steps, sys.stderr))
    assert {t.name for t in tools} == {'list_courses', 'search_course', 'get_source_context', 'get_slide_occurrences'}
    text = render(init, tools, recorded, '循環佇列（本機原創端到端成果）' if args.circular_queue
                  else '堆疊與佇列公開示範')
    for secret in {str(ROOT), ROOT.as_posix(), str(Path.home()), Path.home().as_posix(), 'Traceback'}:
        if secret in text:
            raise AssertionError('record would leak a local path or traceback')
    if args.check or not args.out:
        print(f'MCP demo check passed: protocol {init.protocol_version}, {len(recorded)} tool calls', file=sys.stderr)
        return 0
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + '\n', encoding='utf-8')
    print(f'Recorded {len(recorded)} tool calls', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
