import path from 'node:path';
import { execFileSync } from 'node:child_process';

export default function cleanup() {
  execFileSync('uv', ['run', '--no-sync', '--cache-dir', '.cache/uv', 'python', 'tests/support/browser_api_server.py', '--cleanup'], {
    cwd: path.resolve(import.meta.dirname, '../..'),
    env: process.env,
    stdio: 'inherit',
  });
}
