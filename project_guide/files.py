"""Bounded filesystem reads shared by the picker and Codex tools. Never writes."""
import os
from pathlib import Path, PureWindowsPath


class GuideError(Exception):
    pass


EXCLUDED = {'.git', '.codex', '.env', 'node_modules', 'venv', '.venv', '__pycache__',
            'dist', 'build', '.next', '.idea', '.vscode'}
MAX_FILE = 1024 * 1024
MAX_FILES = 10000


class ProjectFiles:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise GuideError('Select an existing project folder.')

    def resolve(self, relative, *, exists=False):
        if not isinstance(relative, str) or not relative or '\x00' in relative:
            raise GuideError('Invalid project path.')
        win = PureWindowsPath(relative)
        parts = relative.replace('\\', '/').split('/')
        if (win.drive or win.root or Path(relative).is_absolute() or
                any(p == '..' or ':' in p or p.lower() in EXCLUDED or
                    p.lower().startswith('.env.') or p.endswith((' ', '.')) or
                    PureWindowsPath(p).is_reserved() for p in parts if p)):
            raise GuideError('Path is outside the permitted project files.')
        try:
            path = (self.root / relative).resolve(strict=exists)
            path.relative_to(self.root)
        except (OSError, ValueError, RuntimeError) as exc:
            raise GuideError('File is missing or resolves outside the selected project.') from exc
        # Also check the resolved target (a link must not bypass exclusions).
        if any(p.lower() in EXCLUDED or p.lower().startswith('.env.')
               for p in path.relative_to(self.root).parts):
            raise GuideError('This project path is excluded.')
        return path

    def read(self, relative):
        path = self.resolve(relative, exists=True)
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise GuideError('Select a text file smaller than 1 MiB.')
        try:
            raw = path.read_bytes()
            if len(raw) > MAX_FILE or b'\x00' in raw:
                raise GuideError('This is not a supported text file.')
            return raw.decode('utf-8-sig')
        except (OSError, UnicodeError) as exc:
            raise GuideError('Cannot read this file as UTF-8 text.') from exc

    def paths(self):
        count = 0
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d.lower() not in EXCLUDED and
                             not (Path(directory) / d).is_symlink() and
                             not getattr(Path(directory) / d, 'is_junction', lambda: False)())
            for name in sorted(names):
                relative = (Path(directory) / name).relative_to(self.root).as_posix()
                try:
                    self.resolve(relative, exists=True)
                except GuideError:
                    continue
                count += 1
                if count > MAX_FILES:
                    raise GuideError('Project exceeds 10,000 files. Select a smaller workspace folder.')
                yield relative

    def search(self, text, offset=0):
        if not isinstance(text, str) or not text or len(text) > 200:
            raise GuideError('Search requires 1–200 characters of literal text.')
        hits = []
        for relative in self.paths():
            try:
                content = self.read(relative)
            except GuideError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if text.casefold() in line.casefold():
                    hits.append({'path': relative, 'line': number, 'text': line[:500]})
                    if len(hits) >= offset + 100:
                        return hits[offset:]
        return hits[offset:]
