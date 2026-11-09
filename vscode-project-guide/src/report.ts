import {TerminalOutput} from './terminal';

export interface WorkspaceReport {
  terminals: TerminalOutput[];
  terminal: TerminalOutput | null;
  diagnostics: unknown[];
  [key: string]: unknown;
}

const MAX_REPORT_BYTES = 1024 * 1024;
const MAX_DIAGNOSTIC_BYTES = 128 * 1024;
const bytes = (value: unknown): number => Buffer.byteLength(JSON.stringify(value), 'utf8');

/** Clip a suffix by JSON-encoded UTF-8 bytes, never splitting a surrogate pair. */
function outputSuffix(text: string, budget: number): string {
  if (bytes(text) - 2 <= budget) return text;
  const characters = Array.from(text);
  let low = 0;
  let high = characters.length;
  while (low < high) {
    const count = Math.ceil((low + high) / 2);
    const suffix = characters.slice(characters.length - count).join('');
    if (bytes(suffix) - 2 <= budget) low = count;
    else high = count - 1;
  }
  return characters.slice(characters.length - low).join('');
}

/** Budget the actual wire representation; never remove terminal identities. */
export function serializeReport(body: WorkspaceReport): string {
  const report: WorkspaceReport = {...body, terminals: body.terminals.map(record => ({...record}))};
  let diagnosticBytes = 2;
  report.diagnostics = [];
  for (const diagnostic of body.diagnostics.slice(0, 500)) {
    const size = bytes(diagnostic) + (report.diagnostics.length ? 1 : 0);
    if (diagnosticBytes + size > MAX_DIAGNOSTIC_BYTES) break;
    report.diagnostics.push(diagnostic);
    diagnosticBytes += size;
  }
  if (report.diagnostics.length !== body.diagnostics.length) report.diagnostics_truncated = true;
  if (bytes(report) > MAX_REPORT_BYTES) {
    // Reserve identity, execution state, and the full legacy active-terminal output.
    const outputs = report.terminals.map(record => record.output);
    for (const record of report.terminals) {
      record.output = '';
      record.truncated = true;
    }
    if (bytes(report) > MAX_REPORT_BYTES && report.diagnostics.length) {
      report.diagnostics = [];
      report.diagnostics_truncated = true;
    }
    const remaining = MAX_REPORT_BYTES - bytes(report);
    // Do not silently alter roots, dirty paths, or identities if metadata itself is oversized.
    if (remaining < 0) throw new Error('Workspace report metadata exceeds bridge byte limit');
    const allowance = Math.max(0, Math.floor(remaining / Math.max(1, outputs.length)) - 1);
    report.terminals.forEach((record, index) => {
      record.output = outputSuffix(outputs[index], allowance);
      record.truncated = body.terminals[index].truncated || record.output !== outputs[index];
    });
  }
  const data = JSON.stringify(report);
  if (Buffer.byteLength(data, 'utf8') > MAX_REPORT_BYTES) throw new Error('Workspace report exceeds bridge byte limit');
  return data;
}
