export interface TerminalOutput {
  name: string;
  cwd: string;
  command: string;
  output: string;
  running: boolean;
  exit_code: number | null;
  truncated: boolean;
}

export function appendOutput(record: TerminalOutput, chunk: string): void {
  const text = record.output + chunk;
  record.truncated ||= text.length > 32000;
  record.output = text.slice(-32000);
}

export function cleanOutput(text: string): string {
  return text.replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}
