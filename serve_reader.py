"""Loopback reader with range media and versioned local edits. No Windows service."""
import argparse
import json
import re
import secrets
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from manual_edits import EditError, ManualEditsStore
from course_config import load_course

ROOT = Path(__file__).resolve().parent


class ReaderHandler(SimpleHTTPRequestHandler):
    def valid_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',
                                            f'localhost:{self.server.server_port}'}

    def json_response(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def api_snapshot(self, snapshot):
        return dict(snapshot, csrf_token=self.server.edit_token)

    def do_GET(self):
        if not self.valid_host():
            return self.json_response(403, {'error': '不允許的本機 Host。'})
        if urlsplit(self.path).path != '/api/transcript-edits':
            return super().do_GET()
        try:
            self.json_response(200, self.api_snapshot(self.server.edits_store.snapshot()))
        except EditError as error:
            self.json_response(error.status, {'error': str(error)})
        except (OSError, ValueError, KeyError, TypeError):
            self.json_response(500, {'error': '無法讀取本地修訂檔；未覆寫任何資料。'})

    def do_POST(self):
        if urlsplit(self.path).path != '/api/transcript-edits':
            return self.json_response(404, {'error': '儲存端點不存在。'})
        origin = 'http://' + self.headers.get('Host', '')
        if (not self.valid_host() or self.headers.get('Origin') != origin
                or self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin')
                or not secrets.compare_digest(self.headers.get('X-LectureThread-Token', '').encode('utf-8'), self.server.edit_token.encode('utf-8'))):
            return self.json_response(403, {'error': '儲存來源或工作階段不符；請重新連線。'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536 or self.headers.get('Transfer-Encoding'):
                raise EditError(400, '請求大小無效。')
            if self.headers.get_content_type() != 'application/json':
                raise EditError(415, '儲存需要 JSON。')
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise EditError(400, '儲存請求格式無效。')
            snapshot = self.server.edits_store.save(request)
            self.json_response(200, self.api_snapshot(snapshot))
        except EditError as error:
            payload = {'error': str(error)}
            if error.snapshot is not None:
                payload['snapshot'] = self.api_snapshot(error.snapshot)
            self.json_response(error.status, payload)
        except (ValueError, UnicodeError):
            self.json_response(400, {'error': 'JSON 格式無效。'})
        except (OSError, KeyError, TypeError):
            self.json_response(500, {'error': '本地修訂寫入失敗，草稿仍保留，請稍後重試。'})

    def send_head(self):
        self.remaining = None
        path = Path(self.translate_path(self.path))
        if not path.is_file():
            return super().send_head()
        file = path.open('rb')
        size = path.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
            if match and any(match.groups()):
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                elif int(last) > 0:
                    start = max(0, size - int(last))
                else:
                    start = size
            else:
                start = size
            if start > end or start >= size:
                file.close()
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return None
        self.send_response(206 if requested else 200)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Cache-Control', 'no-store')
        if requested:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        file.seek(start)
        self.remaining = end - start + 1
        return file

    def copyfile(self, source, outputfile):
        if self.remaining is None:
            return super().copyfile(source, outputfile)
        try:
            while self.remaining:
                chunk = source.read(min(65536, self.remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                self.remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # A reader changing sentence cancels the previous media request.


def create_server(course=None, port=8766):
    course = load_course(course) if not hasattr(course, 'course_dir') else course
    if not course.output_html.is_file():
        raise FileNotFoundError('Reader HTML missing; run build_reader.py --course with this manifest first')
    server = ThreadingHTTPServer(('127.0.0.1', port),
                                partial(ReaderHandler, directory=str(course.web_root)))
    server.edits_store = ManualEditsStore(course.course_dir, course.id)
    server.edit_token = secrets.token_urlsafe(32)
    server.course = course
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--course', type=Path, help='Course JSON manifest; same default as build_reader.py')
    args = parser.parse_args()
    try:
        server = create_server(args.course, args.port)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f'http://127.0.0.1:{server.server_port}/{server.course.url_for(server.course.output_html)}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
