import {randomUUID} from 'node:crypto';

export interface TerminalOutput {
  id: string;
  execution_id: string;
  revision: number;
  name: string;
  cwd: string;
  command: string;
  output: string;
  running: boolean;
  exit_code: number | null;
  truncated: boolean;
}

type EscapeMode = 'text' | 'escape' | 'intermediate' | 'csi' | 'osc' | 'control' | 'oscEnd' | 'controlEnd';
interface ParserState { mode: EscapeMode; carriageReturn: boolean; }
const parsers = new WeakMap<TerminalOutput, ParserState>();

/** Constant-size parser state: control strings are discarded, never buffered. */
function stripFormatting(text: string, state: ParserState): string {
  const output: string[] = [];
  for (const char of text) {
    if (state.mode === 'osc' || state.mode === 'control') {
      if (char === '\x1b') state.mode = state.mode === 'osc' ? 'oscEnd' : 'controlEnd';
      else if (char === '\x9c' || (char === '\x07' && state.mode === 'osc')) state.mode = 'text';
      continue;
    }
    if (state.mode === 'oscEnd' || state.mode === 'controlEnd') {
      if (char === '\\' || char === '\x9c' || (char === '\x07' && state.mode === 'oscEnd')) state.mode = 'text';
      else if (char !== '\x1b') state.mode = state.mode === 'oscEnd' ? 'osc' : 'control';
      continue;
    }
    if (char === '\x1b') { state.mode = 'escape'; continue; }
    if (state.mode === 'escape') {
      if (char === '[') state.mode = 'csi';
      else if (char === ']') state.mode = 'osc';
      else if ('P^_X'.includes(char)) state.mode = 'control';
      else if (char >= ' ' && char <= '/') state.mode = 'intermediate';
      else state.mode = 'text';
      continue;
    }
    if (state.mode === 'intermediate') {
      if (char >= '0' && char <= '~') state.mode = 'text';
      continue;
    }
    if (state.mode === 'csi') {
      if (char >= '@' && char <= '~') state.mode = 'text';
      continue;
    }
    if (char === '\x9b') { state.mode = 'csi'; continue; }
    if (char === '\x9d') { state.mode = 'osc'; continue; }
    if ('\x90\x98\x9e\x9f'.includes(char)) { state.mode = 'control'; continue; }
    if (char === '\r') output.push('\n');
    else if (char !== '\n' || !state.carriageReturn) output.push(char);
    state.carriageReturn = char === '\r';
  }
  return output.join('');
}

export function appendOutput(record: TerminalOutput, chunk: string): void {
  if (!chunk) return;
  record.revision += 1;
  let parser = parsers.get(record);
  if (!parser) {
    parser = {mode: 'text', carriageReturn: false};
    parsers.set(record, parser);
  }
  const text = record.output + stripFormatting(chunk, parser);
  record.truncated ||= text.length > 32000;
  let start = Math.max(0, text.length - 32000);
  if (start > 0 && text.charCodeAt(start - 1) >= 0xd800 && text.charCodeAt(start - 1) <= 0xdbff &&
      text.charCodeAt(start) >= 0xdc00 && text.charCodeAt(start) <= 0xdfff) start += 1;
  record.output = text.slice(start);
}

export function cleanOutput(text: string): string {
  return stripFormatting(text, {mode: 'text', carriageReturn: false});
}


/** Latest execution per open terminal; terminal identity survives command changes. */
export class TerminalCaptures {
  private readonly ids = new WeakMap<object, string>();
  private readonly records = new Map<object, TerminalOutput>();

  start(terminal: object, name: string, cwd: string, command: string): TerminalOutput {
    const id = this.ids.get(terminal) ?? randomUUID();
    this.ids.set(terminal, id);
    const record: TerminalOutput = {id, execution_id: randomUUID(), revision: 0,
      name: name.slice(0, 200), cwd: cwd.slice(0, 4000), command: command.slice(0, 2000),
      output: '', running: true, exit_code: null, truncated: false};
    this.records.delete(terminal);
    this.records.set(terminal, record);
    return record;
  }

  active(terminal: object | undefined): TerminalOutput | null {
    const record = terminal && this.records.get(terminal);
    return record ? {...record, output: cleanOutput(record.output)} : null;
  }

  list(): TerminalOutput[] {
    return [...this.records.values()].slice(-20).map(record => ({...record, output: cleanOutput(record.output)}));
  }

  close(terminal: object): void { this.records.delete(terminal); }
  clear(): void { this.records.clear(); }
}
