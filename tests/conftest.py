"""Shared pytest switches.

Without FFmpeg the synthetic-video tests skip with an explicit reason. CI sets
LECTURETHREAD_REQUIRE_FFMPEG=1 so a missing tool fails the run instead.
"""
import os
import shutil

import pytest


def _require_ffmpeg():
    return os.environ.get('LECTURETHREAD_REQUIRE_FFMPEG') == '1'


def pytest_configure(config):
    if _require_ffmpeg():
        missing = [name for name in ('ffmpeg', 'ffprobe') if not shutil.which(name)]
        if missing:
            raise pytest.UsageError('LECTURETHREAD_REQUIRE_FFMPEG=1 but not on PATH: ' + ', '.join(missing))


def pytest_sessionfinish(session, exitstatus):
    if not _require_ffmpeg():
        return
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    skipped = reporter.stats.get('skipped', []) if reporter else []
    ffmpeg_skips = [r.nodeid for r in skipped if 'ffmpeg' in str(r.longrepr).lower()]
    if ffmpeg_skips:
        if reporter:
            reporter.write_line('FFmpeg tests skipped although required: ' + ', '.join(ffmpeg_skips), red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
