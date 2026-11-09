import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {TerminalOutput, appendOutput, cleanOutput} from './terminal';

test('terminal output is bounded and truncation remains explicit', () => {
  const record: TerminalOutput = {id: 't', execution_id: 'e', revision: 0, name: 'pwsh', cwd: 'C:/project', command: 'test',
    output: '', running: true, exit_code: null, truncated: false};
  appendOutput(record, 'x'.repeat(33000));
  appendOutput(record, '\nFAIL');
  assert.equal(record.output.length, 32000);
  assert.ok(record.output.endsWith('\nFAIL'));
  assert.equal(record.truncated, true);
});

test('terminal formatting does not obscure errors', () => {
  assert.equal(cleanOutput('\x1b[31mFAIL\x1b[0m\r\n\x1b]0;title\x07details'), 'FAIL\ndetails');
});

test('hyperlink escape sequences preserve linked error messages', () => {
  assert.equal(cleanOutput('\x1b]8;;https://example.test\x1b\\FAIL: missing module\x1b]8;;\x1b\\\n1 failed'),
    'FAIL: missing module\n1 failed');
});


test('only nonempty chunks advance output revision', () => {
  const record = {id: 't', execution_id: 'e', revision: 0, name: 'pwsh', cwd: '',
    command: '', output: '', running: true, exit_code: null, truncated: false};
  appendOutput(record, '');
  assert.equal(record.revision, 0);
  appendOutput(record, 'hello');
  assert.equal(record.revision, 1);
  appendOutput(record, '');
  assert.equal(record.revision, 1);
  appendOutput(record, 'world');
  assert.equal(record.revision, 2);
});

test('capture lifecycle keeps terminal identity, isolates executions, and removes closed terminals', () => {
  const {TerminalCaptures} = require('./terminal');
  const captures = new TerminalCaptures();
  const terminal = {};
  const first = captures.start(terminal, 'pwsh', 'C:/project', 'first');
  appendOutput(first, 'old');
  const second = captures.start(terminal, 'pwsh', 'C:/project', 'second');
  assert.equal(first.id, second.id);
  assert.notEqual(first.execution_id, second.execution_id);
  assert.equal(second.revision, 0);
  appendOutput(first, 'late old output');
  appendOutput(second, '\x1b[31mnew\x1b[0m');
  assert.equal(captures.active(terminal).output, 'new');
  assert.equal(captures.list()[0].revision, 1);
  captures.close(terminal);
  assert.deepEqual(captures.list(), []);
  assert.equal(captures.active(terminal), null);
});

test('reports bound terminal count and preserve active terminal compatibility', () => {
  const {TerminalCaptures} = require('./terminal');
  const captures = new TerminalCaptures();
  const oldest = {};
  captures.start(oldest, 'first', 'C:/project', 'test');
  for (let i = 0; i < 25; i++) captures.start({}, 'other', 'C:/project', 'test');
  assert.equal(captures.list().length, 20);
  assert.equal(captures.active(oldest).name, 'first');
  captures.clear();
  assert.deepEqual(captures.list(), []);
  assert.equal(captures.active(oldest), null);
});

test('multilingual reports fit HTTP byte cap without losing terminal identities or legacy output', () => {
  const {serializeReport} = require('./report');
  for (const text of ['\u754c'.repeat(32000), '\u{1f642}'.repeat(16000), '\"\\\u0000'.repeat(8000)]) {
    const terminals = Array.from({length: 20}, (_, i) => ({id: `t-${i}`, execution_id: `e-${i}`,
      revision: 7, name: '\u7aef\u672b', cwd: 'C:/project', command: 'test', output: text,
      running: true, exit_code: null, truncated: false}));
    const body = {window: 'one', roots: ['C:/project'], remote: false, trusted: true,
      terminal: {...terminals[0]}, terminals,
      diagnostics: Array.from({length: 500}, () => ({path: 'C:/project/file.ts',
        line: 1, severity: 0, message: '\u754c'.repeat(2000)})), dirty: [], ack: 'fresh'};
    const original = JSON.stringify(body);
    const encoded = serializeReport(body);
    assert.ok(Buffer.byteLength(encoded, 'utf8') <= 1024 * 1024);
    const report = JSON.parse(encoded);
    assert.equal(report.terminal.output, text);
    assert.equal(report.terminal.truncated, false);
    assert.equal(report.terminals.length, 20);
    for (let i = 0; i < 20; i++) {
      const record = report.terminals[i];
      assert.equal(record.id, `t-${i}`);
      assert.equal(record.execution_id, `e-${i}`);
      assert.equal(record.revision, 7);
      assert.equal(record.running, true);
      assert.ok(record.output.length > 0);
      assert.ok(text.endsWith(record.output));
      assert.equal(record.truncated, record.output !== text);
      assert.ok(!/^[\uDC00-\uDFFF]/u.test(record.output));
    }
    assert.equal(report.ack, 'fresh');
    assert.ok(report.diagnostics.length < 500);
    assert.equal(report.diagnostics_truncated, true);
    assert.equal(JSON.stringify(body), original);
  }
});

test('small reports preserve complete evidence without truncation', () => {
  const {serializeReport} = require('./report');
  const body = {window: 'one', terminals: [], terminal: null, diagnostics: [], dirty: []};
  assert.deepEqual(JSON.parse(serializeReport(body)), body);
});

test('TUI capture removes cursor, charset, keypad, and device control sequences', () => {
  assert.equal(cleanOutput('\x1b[?1049h\x1b[2J\x1b[H\x1b(B\x1b=menu\r\n'
    + '\x1bPdevice data\x1b\\\x1b[31mERROR\x1b[0m\x1b[?25l'), 'menu\nERROR');
});


test('ANSI-only volume does not consume the captured text limit', () => {
  const {TerminalCaptures} = require('./terminal');
  const captures = new TerminalCaptures();
  const terminal = {};
  const record = captures.start(terminal, 'pwsh', 'C:/project', 'test');
  appendOutput(record, '\x1b[0m'.repeat(8001) + 'Done');
  assert.equal(record.output, 'Done');
  assert.equal(record.truncated, false);
  assert.equal(captures.active(terminal).truncated, false);
});

test('split ANSI and CRLF retain text while arbitrarily long control strings stay bounded', () => {
  const {TerminalCaptures} = require('./terminal');
  const captures = new TerminalCaptures();
  const record = captures.start({}, 'pwsh', 'C:/project', 'test');
  for (const chunk of ['\x1b', '[31', 'mError', '\x1b]0;', 'x'.repeat(100000),
    '\x1b', '\\', '\r', '\nDone', '\x1b(', 'B']) appendOutput(record, chunk);
  assert.equal(record.output, 'Error\nDone');
  assert.equal(record.truncated, false);
  appendOutput(record, '\x1b[0m' + 'z'.repeat(32001));
  assert.equal(record.output, 'z'.repeat(32000));
  assert.equal(record.truncated, true);
});


test('capture suffix never splits a surrogate pair at the text limit', () => {
  const {TerminalCaptures} = require('./terminal');
  for (const chunks of [['\u{1f642}' + 'x'.repeat(31999)], ['\u{1f642}', 'x'.repeat(31999)]]) {
    const record = new TerminalCaptures().start({}, 'pwsh', 'C:/project', 'test');
    for (const chunk of chunks) appendOutput(record, chunk);
    assert.equal(record.output.length, 31999);
    assert.equal(record.output.charCodeAt(0), 120);
    assert.equal(record.truncated, true);
    assert.equal(Buffer.from(record.output, 'utf8').toString('utf8'), record.output);
  }
  const record = new TerminalCaptures().start({}, 'pwsh', 'C:/project', 'test');
  appendOutput(record, 'a\u{1f642}' + 'x'.repeat(31998));
  assert.equal(record.output.length, 32000);
  assert.ok(record.output.startsWith('\u{1f642}'));
  // A preexisting lone surrogate is not a pair split by this cutoff.
  const unpaired = new TerminalCaptures().start({}, 'pwsh', 'C:/project', 'test');
  appendOutput(unpaired, 'a\udc00' + 'x'.repeat(31999));
  assert.equal(unpaired.output.charCodeAt(0), 0xdc00);
});
