import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {TerminalOutput, appendOutput, cleanOutput} from './terminal';

test('terminal output is bounded and truncation remains explicit', () => {
  const record: TerminalOutput = {name: 'pwsh', cwd: 'C:/project', command: 'test',
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
