"""Minimal stdio MCP server with exactly three read-only tools; no execution API."""
import json
import sys
import os
from .files import GuideError, ProjectFiles


TOOLS = [
    {'name': 'list_files', 'description': 'List project paths, 500 per page. Excludes dependencies and private configuration.',
     'inputSchema': {'type': 'object', 'properties': {'offset': {'type': 'integer', 'minimum': 0}}, 'additionalProperties': False}},
    {'name': 'read_file', 'description': 'Read saved UTF-8 text with line numbers. Use offset to continue a long file.',
     'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}},
                     'required': ['path'], 'additionalProperties': False}},
    {'name': 'search_text', 'description': 'Search literal text in saved project files, 100 matches per page.',
     'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}},
                     'required': ['text'], 'additionalProperties': False}},
]
for tool in TOOLS:
    tool['annotations'] = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}


def dispatch(files, method, params):
    if method == 'initialize':
        return {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'ai-live-project-reader', 'version': '0.1.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method != 'tools/call':
        raise GuideError('Unsupported read-only method.')
    name, args = params.get('name'), params.get('arguments', {})
    if not isinstance(args, dict):
        raise GuideError('Invalid tool arguments.')
    offset = args.get('offset', 0)
    if type(offset) is not int or not 0 <= offset <= 100000:
        raise GuideError('Invalid offset.')
    if name == 'list_files':
        paths = list(files.paths())
        value = {'paths': paths[offset:offset + 500], 'total': len(paths)}
    elif name == 'read_file':
        lines = files.read(args.get('path')).splitlines()
        value = {'path': args['path'], 'total_lines': len(lines),
                 'lines': [f'{n + 1}: {line}' for n, line in enumerate(lines) if offset <= n < offset + 300]}
    elif name == 'search_text':
        value = files.search(args.get('text'), offset)
    else:
        raise GuideError('Only list_files, read_file and search_text are available.')
    return {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}


def main(root):
    if os.name == 'nt' and (sys.stdin is None or sys.stdout is None):
        # PyInstaller --windowed removes Python streams, but a parent MCP process
        # still supplies real Win32 pipe handles. Reattach those without a console.
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        if sys.stdin is None:
            descriptor = msvcrt.open_osfhandle(kernel.GetStdHandle(-10), os.O_RDONLY)
            sys.stdin = open(descriptor, 'r', encoding='utf-8')
        if sys.stdout is None:
            descriptor = msvcrt.open_osfhandle(kernel.GetStdHandle(-11), os.O_WRONLY)
            sys.stdout = open(descriptor, 'w', encoding='utf-8')
    files = ProjectFiles(root)
    for raw in sys.stdin:
        message = None
        try:
            if len(raw) > 1024 * 1024:
                raise GuideError('Request too large.')
            message = json.loads(raw)
            if 'id' not in message:
                continue
            result = dispatch(files, message['method'], message.get('params', {}))
            response = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
        except (ValueError, KeyError, TypeError, OSError, GuideError) as exc:
            response = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                        'error': {'code': -32602, 'message': str(exc)}}
        sys.stdout.write(json.dumps(response, ensure_ascii=True) + '\n')
        sys.stdout.flush()
