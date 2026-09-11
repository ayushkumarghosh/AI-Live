import * as path from 'node:path';
import * as fs from 'node:fs/promises';

export type Connection = {url: string; token: string; version: number};
export type OpenCommand = {type: 'open'; root: string; path: string; line: number};

export function validConnection(value: unknown): value is Connection {
  if (!value || typeof value !== 'object') return false;
  const c = value as Connection;
  return c.version === 1 && typeof c.token === 'string' && c.token.length >= 32 &&
    typeof c.url === 'string' && /^http:\/\/127\.0\.0\.1:[0-9]{1,5}$/.test(c.url);
}

export function validateOpen(value: unknown, roots: readonly string[]): value is OpenCommand {
  if (!value || typeof value !== 'object') return false;
  const c = value as OpenCommand;
  if (c.type !== 'open' || typeof c.root !== 'string' || typeof c.path !== 'string' ||
      !Number.isInteger(c.line) || c.line < 1 || !path.win32.isAbsolute(c.path)) return false;
  if (!roots.some(r => path.win32.resolve(r).toLowerCase() === path.win32.resolve(c.root).toLowerCase())) return false;
  const relative = path.win32.relative(c.root, c.path);
  return !!relative && !relative.startsWith('..') && !path.win32.isAbsolute(relative) && !relative.includes(':');
}

export async function resolveOpen(value: unknown, roots: readonly string[]): Promise<OpenCommand | undefined> {
  const canonicalRoots = await Promise.all(roots.map(root => fs.realpath(root)));
  if (!validateOpen(value, canonicalRoots)) return undefined;
  const canonicalRoot = await fs.realpath(value.root);
  const canonicalPath = await fs.realpath(value.path);
  const command = {...value, root: canonicalRoot, path: canonicalPath};
  return validateOpen(command, canonicalRoots) ? command : undefined;
}
