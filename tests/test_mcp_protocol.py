"""Real MCP client/server checks: the official SDK client launches lecture_mcp_server.py over stdio.

Calling course_query functions directly is not an MCP acceptance test; every
case here goes through a spawned server process and the JSON-RPC wire.
"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil
import pytest

pytest.importorskip('mcp', reason='MCP SDK not installed; install requirements-dev.txt')

from mcp import Client, ClientSession, StdioServerParameters, stdio_client  # noqa: E402
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS  # noqa: E402

from test_course_query import demo_course, registry, synthetic_course, tree_state, write_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable).resolve()
SERVER = ROOT / 'lecture_mcp_server.py'
TOOLS = {'list_courses', 'search_course', 'get_source_context', 'get_slide_occurrences'}


@pytest.fixture
def workspace():
    parent = ROOT / 'data/tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mcp-protocol-', dir=parent) as folder:
        yield Path(folder)


@pytest.fixture
def setup(workspace):
    first = synthetic_course(workspace / 'a', 'synthetic')
    second = demo_course(workspace / 'b')
    reg = registry(workspace, [dict(manifest='a/' + first.name, raw_transcript_origin='asr'),
                               dict(manifest='b/' + second.name, raw_transcript_origin='scripted')])
    elsewhere = workspace / 'unrelated-cwd'
    elsewhere.mkdir()
    return reg, elsewhere, workspace


def params(reg, cwd):
    # Absolute interpreter, script and registry; the client's cwd is deliberately unrelated.
    return StdioServerParameters(command=str(PYTHON), args=[str(SERVER), '--registry', str(reg)], cwd=str(cwd))


def server_children():
    return [p for p in psutil.Process().children(recursive=True)
            if any('lecture_mcp_server.py' in part for part in _cmdline(p))]


def _cmdline(process):
    try:
        return process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def payload(result):
    """structured_content and the text block must carry the same JSON."""
    assert json.loads(result.content[0].text) == result.structured_content
    return result.structured_content


def test_full_tool_result_budget_over_stdio(setup):
    reg, cwd, root = setup
    rows = [dict(start=i, end=i + 1, text='佇列' + '甲' * 598) for i in range(30)]
    for name in ('transcript.json', 'transcript.corrected.json'):
        write_json(root / 'a/web/course' / name, rows)

    async def exercise():
        async with stdio_client(params(reg, cwd)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                seen, cursor, shortened = [], None, False
                while True:
                    result = await session.call_tool('search_course', dict(
                        course_id='synthetic', query='佇列', layer='raw_transcript', limit=20, cursor=cursor))
                    assert not result.is_error
                    assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode('utf-8')) <= 65536
                    page = payload(result)
                    shortened |= any(w['code'] == 'page_shortened_for_size' for w in page['warnings'])
                    seen.extend(r['source_id'] for r in page['data']['results'])
                    cursor = page['data']['next_cursor']
                    if cursor is None:
                        break
                assert seen == list(range(30)) and shortened
                # This payload fits alone, but its text + structured copies do not.
                result = await session.call_tool('get_source_context', dict(
                    course_id='synthetic', source_ids=list(range(10)), before=0, after=0))
                assert result.is_error and payload(result)['error']['code'] == 'RESULT_TOO_LARGE'
                assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode('utf-8')) <= 65536
                small = await session.call_tool('get_source_context', dict(
                    course_id='synthetic', source_ids=[0], before=0, after=0))
                assert not small.is_error
                assert len(small.model_dump_json(by_alias=True, exclude_none=True).encode('utf-8')) <= 65536
    asyncio.run(exercise())


def test_adapter_budget_includes_escaping_and_oversized_errors():
    from course_query import encoded_size
    from lecture_mcp_server import _result
    data = {'text': '中文"\\\n' * 100}
    result = _result(data)
    assert encoded_size(data) == len(result.model_dump_json(by_alias=True, exclude_none=True).encode('utf-8'))
    for is_error in (False, True):
        result = _result({'details': '甲' * 30000}, is_error=is_error)
        assert result.is_error and payload(result)['error']['code'] == 'RESULT_TOO_LARGE'
        assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode('utf-8')) <= 65536


async def session_flow(reg, cwd, errlog):
    async with stdio_client(params(reg, cwd), errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            calls = {}
            calls['list'] = await session.call_tool('list_courses', {})
            calls['search'] = await session.call_tool('search_course', {'course_id': 'synthetic', 'query': '環狀佇列'})
            revision = calls['search'].structured_content['revision']
            calls['context'] = await session.call_tool('get_source_context', {
                'course_id': 'synthetic', 'source_ids': [2], 'before': 0, 'after': 1, 'expected_revision': revision})
            calls['occurrences'] = await session.call_tool('get_slide_occurrences',
                                                           {'course_id': 'synthetic', 'page_id': 'p:1'})
            calls['demo_occurrences'] = await session.call_tool('get_slide_occurrences',
                                                                {'course_id': 'lecturethread-demo'})
            calls['empty'] = await session.call_tool('search_course', {'course_id': 'synthetic', 'query': '紅黑樹'})
            calls['not_allowed'] = await session.call_tool('search_course', {'course_id': 'private', 'query': 'x'})
            calls['missing_id'] = await session.call_tool('get_source_context',
                                                          {'course_id': 'synthetic', 'source_ids': [999]})
            calls['bool_id'] = await session.call_tool('get_source_context',
                                                       {'course_id': 'synthetic', 'source_ids': [True]})
            calls['stale'] = await session.call_tool('get_slide_occurrences',
                                                     {'course_id': 'synthetic', 'expected_revision': 'r1-old'})
            calls['layer'] = await session.call_tool('search_course', {
                'course_id': 'lecturethread-demo', 'query': 'stack', 'layer': 'editorial_notes'})
            alive_during = len(server_children())
    return init, tools, calls, alive_during


def test_sdk_client_lists_and_calls_all_four_tools_over_stdio(setup):
    reg, cwd, workspace = setup
    before = tree_state(workspace / 'a') | {('demo/' + k): v for k, v in tree_state(workspace / 'b').items()}
    log = workspace / 'server.stderr.log'
    with log.open('w', encoding='utf-8') as errlog:
        init, tools, calls, alive_during = asyncio.run(session_flow(reg, cwd, errlog))

    assert init.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS
    assert init.server_info.name == 'lecturethread' and init.instructions
    assert {t.name for t in tools} == TOOLS
    by_name = {t.name: t for t in tools}
    for tool in tools:
        assert tool.annotations.read_only_hint is True and tool.annotations.destructive_hint is False
        assert tool.input_schema['type'] == 'object'
    assert set(by_name['search_course'].input_schema['required']) == {'course_id', 'query'}
    assert by_name['search_course'].input_schema['properties']['layer']['enum'] == [
        'raw_transcript', 'corrected_transcript', 'editorial_notes']
    assert by_name['get_source_context'].input_schema['properties']['source_ids']['maxItems'] == 10
    assert by_name['get_slide_occurrences'].input_schema['properties']['limit']['maximum'] == 50

    listing = payload(calls['list'])
    assert [c['id'] for c in listing['data']['courses']] == ['synthetic', 'lecturethread-demo']
    hit = payload(calls['search'])['data']['results'][0]
    assert (hit['source_id'], hit['start'], hit['end']) == (2, 11, 17)
    source = payload(calls['context'])['data']['sources'][0]
    assert [o['occurrence_id'] for o in source['occurrences']] == [2, 3]
    assert [s['source_id'] for s in source['context_after']] == [3]
    revisits = payload(calls['occurrences'])['data']['occurrences']
    assert [o['occurrence_id'] for o in revisits] == [1, 4, 5]
    demo = payload(calls['demo_occurrences'])
    assert all(o['page_id'] is None for o in demo['data']['occurrences'])

    # Empty results are successes; business errors are tool errors with a stable code.
    assert calls['empty'].is_error is False and payload(calls['empty'])['data']['results'] == []
    for name, code in (('not_allowed', 'COURSE_NOT_ALLOWED'), ('missing_id', 'SOURCE_NOT_FOUND'),
                       ('stale', 'STALE_REVISION'), ('layer', 'LAYER_UNAVAILABLE')):
        assert calls[name].is_error is True, name
        assert payload(calls[name])['error']['code'] == code
    assert calls['bool_id'].is_error is True  # rejected by the SDK's schema validation

    text = json.dumps({k: v.structured_content for k, v in calls.items()}, ensure_ascii=False)
    for secret in (str(workspace), str(ROOT), str(Path.home()), 'Traceback'):
        assert secret not in text
    assert alive_during >= 1           # the venv launcher may add a parent process on Windows
    assert server_children() == []      # the client closed the server; nothing keeps running
    after = tree_state(workspace / 'a') | {('demo/' + k): v for k, v in tree_state(workspace / 'b').items()}
    assert after == before               # no writes, no lock files
    assert 'serving 2 registered course(s)' in log.read_text(encoding='utf-8')


def test_high_level_client_negotiates_the_modern_protocol_too(setup):
    reg, cwd, workspace = setup

    async def flow(errlog):
        async with Client(params(reg, cwd)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            result = await client.call_tool('search_course', {'course_id': 'lecturethread-demo', 'query': 'LIFO',
                                                              'layer': 'raw_transcript'})
            return client.protocol_version, names, result

    with (workspace / 'stderr.log').open('w', encoding='utf-8') as errlog:
        old_stderr, sys.stderr = sys.stderr, errlog   # Client uses stdio_client's default errlog
        try:
            version, names, result = asyncio.run(flow(errlog))
        finally:
            sys.stderr = old_stderr
    assert version in HANDSHAKE_PROTOCOL_VERSIONS + MODERN_PROTOCOL_VERSIONS
    assert names == TOOLS
    data = payload(result)
    assert [r['source_id'] for r in data['data']['results']] == [0, 5]
    assert any(w['code'] == 'scripted_transcript' for w in data['warnings'])
    assert server_children() == []


def _rpc(process, message):
    process.stdin.write((json.dumps(message) + '\n').encode())
    process.stdin.flush()


def test_stdout_carries_only_protocol_messages_and_server_exits_when_stdin_closes(setup):
    reg, cwd, workspace = setup
    log = workspace / 'raw.stderr.log'
    with log.open('wb') as errlog:
        process = subprocess.Popen([str(PYTHON), str(SERVER), '--registry', str(reg)], cwd=cwd,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog)
        try:
            requests = [
                dict(jsonrpc='2.0', id=1, method='initialize', params=dict(
                    protocolVersion=HANDSHAKE_PROTOCOL_VERSIONS[-1], capabilities={},
                    clientInfo=dict(name='raw-test', version='0'))),
                dict(jsonrpc='2.0', id=2, method='tools/list'),
                dict(jsonrpc='2.0', id=3, method='tools/call',
                     params=dict(name='get_slide_occurrences', arguments=dict(course_id='synthetic')))]
            messages = []
            for request in requests:
                _rpc(process, request)
                if request['id'] == 1:
                    _rpc(process, dict(jsonrpc='2.0', method='notifications/initialized'))
                # The very next stdout line must be this response: any log line would fail to parse.
                messages.append(json.loads(process.stdout.readline().decode('utf-8')))
            process.stdin.close()            # the client disconnects
            process.wait(timeout=30)
            rest = process.stdout.read()
        finally:
            if process.poll() is None:
                process.kill()
    assert process.returncode == 0
    assert rest.strip() == b''
    assert all(m.get('jsonrpc') == '2.0' for m in messages)
    assert [m.get('id') for m in messages] == [1, 2, 3]
    assert len(messages[1]['result']['tools']) == 4
    assert messages[2]['result']['isError'] is False
    assert b'serving 2 registered course(s)' in log.read_bytes()


def test_bad_registry_fails_fast_on_stderr_without_protocol_output(workspace):
    reg = workspace / 'registry.json'
    reg.write_text(json.dumps(dict(schema=1, courses=[dict(manifest='missing.json')])), encoding='utf-8')
    started = time.monotonic()
    result = subprocess.run([str(PYTHON), str(SERVER), '--registry', str(reg)], cwd=workspace,
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert result.returncode == 2 and result.stdout == b''
    assert b'cannot load course registry' in result.stderr and b'Traceback' not in result.stderr
    assert time.monotonic() - started < 60


def test_example_registry_lists_only_the_public_demo():
    doc = json.loads((ROOT / 'mcp.courses.example.json').read_text(encoding='utf-8'))
    assert doc == dict(schema=1, courses=[dict(manifest='courses/demo.json', raw_transcript_origin='scripted')])
    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    assert 'mcp.courses.local.json' in gitignore
