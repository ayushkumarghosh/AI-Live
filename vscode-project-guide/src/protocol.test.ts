import {strict as assert} from 'node:assert';
import {test} from 'node:test';
import {validConnection, validateOpen, resolveOpen} from './protocol';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

test('discovery only accepts loopback and a bearer token', () => {
  assert.equal(validConnection({url: 'http://127.0.0.1:1234', token: 'a'.repeat(32), version: 1}), true);
  assert.equal(validConnection({url: 'https://example.com', token: 'a'.repeat(32), version: 1}), false);
});

test('a workspace opened through a junction resolves to its selected root', {skip: process.platform !== 'win32'}, async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'ai-live-junction-'));
  try {
    const root = path.join(temp, 'project');
    const link = path.join(temp, 'linked');
    await fs.mkdir(root);
    await fs.writeFile(path.join(root, 'a.txt'), 'test');
    await fs.symlink(root, link, 'junction');
    const command = await resolveOpen({type: 'open', root, path: path.join(root, 'a.txt'), line: 1}, [link]);
    assert.equal(command?.path, path.join(root, 'a.txt'));
  } finally {
    await fs.rm(temp, {recursive: true, force: true});
  }
});
test('only contained file opening is accepted', () => {
  const root = 'C:\\work';
  assert.equal(validateOpen({type: 'open', root, path: 'C:\\work\\a.ts', line: 2}, [root]), true);
  for (const command of [
    {type: 'execute', root, path: 'C:\\work\\a.ts', line: 1},
    {type: 'open', root, path: 'C:\\work2\\a.ts', line: 1},
    {type: 'open', root, path: 'C:\\work\\..\\secret', line: 1},
    {type: 'open', root, path: 'C:\\work\\a.ts:stream', line: 1},
  ]) assert.equal(validateOpen(command, [root]), false);
});
