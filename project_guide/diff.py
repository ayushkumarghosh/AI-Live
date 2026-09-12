"""Display supplied unified patches without changing their contents or applying them."""
import html
import re

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.util import ClassNotFound


HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def diff_rows(patch):
    """Yield old number, new number, change marker, and literal line content."""
    old = new = old_left = new_left = 0
    for line in patch.splitlines():
        match = HUNK.match(line)
        if match:
            old, new = int(match[1]), int(match[3])
            old_left = int(match[2]) if match[2] is not None else 1
            new_left = int(match[4]) if match[4] is not None else 1
        elif (old_left or new_left) and line[:1] in (' ', '-', '+'):
            marker = line[0]
            yield (old if marker != '+' else '', new if marker != '-' else '', marker, line[1:])
            if marker != '+':
                old += 1
                old_left = max(0, old_left - 1)
            if marker != '-':
                new += 1
                new_left = max(0, new_left - 1)
            continue
        yield '', '', '', line


def render_guide_diff(patch, path, *, grid=False):
    try:
        lexer = get_lexer_for_filename(path, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False, ensurenl=False)
    formatter = HtmlFormatter(noclasses=True, style='monokai', nowrap=True)
    rows = []
    grid_rows = ['  Old   New   Changes']
    for old, new, marker, text in diff_rows(patch):
        marker_color = {'+': '#8bd49c', '-': '#f08080'}.get(marker, '#c4cdd7')
        if marker:
            content = highlight(text, lexer, formatter)
        else:
            content = html.escape(text)
        if grid:
            prefix = html.escape(f'{old:>5} {new:>5} {marker or " ":>2} ')
            grid_rows.append(f'<span style="color:{marker_color};">{prefix}</span>'
                             + (content.rstrip('\n') or ' '))
            continue
        cells = ''.join(f'<td width="55" align="right" style="color:#8d9baa;padding:0 8px;">'
                        f'<pre style="margin:0;">{number}</pre></td>'
                        for number in (old, new))
        rows.append(f'<tr>{cells}'
                    f'<td width="20" style="color:{marker_color};padding:0 6px;">{marker}</td>'
                    '<td><pre style="margin:0;color:#e8eef5;'
                    'font-family:Consolas, Cascadia Mono, monospace;font-size:14px;">'
                    + (content or ' ') + '</pre></td></tr>')
    if grid:
        return '<pre style="margin:0;">' + '\n'.join(grid_rows) + '</pre>'
    return ('<table width="100%" cellspacing="0" cellpadding="0" '
            'style="font-family:Consolas, monospace;font-size:14px;">'
            '<tr style="color:#8d9baa;">'
            '<td width="55" align="right">Old</td><td width="55" align="right">New</td>'
            '<td width="20"></td><td>Changes</td></tr>'
            + ''.join(rows) + '</table>')
