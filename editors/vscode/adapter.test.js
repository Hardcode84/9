// SPDX-License-Identifier: Apache-2.0

import { test, expect } from 'bun:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { tokenTypes, tokenModifiers, snapshot, decodeTokens, runHighlighter } from './adapter.cjs';

const executable = process.env.CRUST_HIGHLIGHT;
if (!executable) throw new Error('Run make check-vscode to supply the built highlighter');
const launcher = process.env.CRUST_LAUNCHER;
if (!launcher) throw new Error('Run make check-vscode to supply the source launcher');

function response(text, spans) {
    return { version: 1, byteLength: Buffer.byteLength(text), tokenTypes, tokenModifiers, spans };
}

test('UTF-8 spans become UTF-16 positions across CRLF, CR, and LF', () => {
    const text = 'é😀\r\nx\ry\n';
    const result = decodeTokens(response(text, [[0, Buffer.byteLength(text), 2, 0]]), text);
    expect([...result.data]).toEqual([0, 0, 3, 2, 0, 1, 0, 1, 2, 0, 1, 0, 1, 2, 0]);
    expect(decodeTokens(response('\n', [[0, 1, 11, 0]]), '\n').issues).toEqual([
        { line: 0, start: 0, end: 0, kind: 11 },
    ]);
});

test('external token responses reject invalid ranges, legends, and byte boundaries', () => {
    const text = 'éx';
    for (const spans of [
        [[0, 1, 2, 0]], [[1, 2, 2, 0]], [[0, 4, 2, 0]], [[0, 0, 2, 0]],
        [[0, 2, 2, 0], [0, 2, 2, 0]], [[0, 2, 12, 0]], [[0, 2, 2, 4]],
        [[0, 2, 2, -1]], [[0.5, 2, 2, 0]], [[0, 2, 2]],
    ]) expect(() => decodeTokens(response(text, spans), text)).toThrow();
    expect(() => decodeTokens({ ...response(text, []), version: 2 }, text)).toThrow();
    expect(() => decodeTokens({ ...response(text, []), byteLength: 2 }, text)).toThrow();
    expect(() => decodeTokens({ ...response(text, []), tokenTypes: [] }, text)).toThrow();
    expect(() => snapshot('\ud800')).toThrow('surrogate');
    expect(() => snapshot('x'.repeat(4 * 1024 * 1024 + 1))).toThrow('4 MiB');
});

test('response and multiline token budgets reject excess without truncation', () => {
    const text = 'x\n'.repeat(500000);
    const result = decodeTokens(response(text, [[0, text.length, 2, 0]]), text);
    expect(result.data.length).toBe(500000 * 5);
    expect([...result.data.slice(-5)]).toEqual([1, 0, 1, 2, 0]);
    const excess = text + 'x';
    expect(() => decodeTokens(response(excess, [[0, excess.length, 2, 0]]), excess)).toThrow('semantic token limit');
    const many = 'x'.repeat(500001);
    const spans = Array.from({ length: many.length }, (_, index) => [index, index + 1, 2, 0]);
    expect(() => decodeTokens(response(many, spans), many)).toThrow('span limit');
});

test('native service colors an unsaved Unicode snapshot and recovers after errors', async () => {
    const text = '// 😀é\r\n"unfinished\r\nfn after()->unit{}';
    const raw = await runHighlighter({ executable, text });
    const result = decodeTokens(raw, text);
    expect([...result.data.slice(0, 5)]).toEqual([0, 0, 6, 1, 0]);
    expect(raw.spans.some(([begin, end, kind]) =>
        Buffer.from(text).subarray(begin, end).toString() === 'after' && tokenTypes[kind] === 'function')).toBe(true);
    expect(result.issues).toEqual([{ line: 1, start: 0, end: 11, kind: 10 }]);
});

test('a user Crust program supplies a different grammar through the same process contract', async () => {
    const root = path.resolve(import.meta.dir, '../..');
    const text = await fs.readFile(path.join(root, 'examples/reader-switch/main.crs'), 'utf8');
    const raw = await runHighlighter({
        executable: launcher,
        args: [path.join(root, 'examples/highlight/reader-switch.crs')], text,
    });
    const spans = raw.spans.map(([begin, end, kind]) => [Buffer.from(text).subarray(begin, end).toString(), tokenTypes[kind]]);
    expect(spans).toContainEqual(['Hello from a reader written in CRUST!', 'string']);
    expect(decodeTokens(raw, text).issues).toEqual([]);
});

test('cancellation and timeout stop a running process and remove its snapshot', async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'crust-adapter-test-'));
    const record = path.join(directory, 'record');
    const script = 'import sys,time;open(sys.argv[1],"w").write(sys.argv[-1]);time.sleep(10)';
    try {
        const controller = new AbortController();
        const pending = runHighlighter({ executable: 'python3', args: ['-c', script, record], text: 'fn f()->unit{}', signal: controller.signal });
        let input;
        for (let attempt = 0; attempt < 200; attempt++) {
            try { input = await fs.readFile(record, 'utf8'); break; }
            catch (error) { if (error.code !== 'ENOENT') throw error; }
            await new Promise(resolve => setTimeout(resolve, 5));
        }
        expect(input).toBeTruthy();
        controller.abort();
        await expect(pending).rejects.toThrow('cancelled');
        await expect(fs.stat(path.dirname(input))).rejects.toMatchObject({ code: 'ENOENT' });
        await expect(runHighlighter({ executable: 'python3', args: ['-c', script, record], text: '', timeoutMs: 100 })).rejects.toThrow('timed out');
        input = await fs.readFile(record, 'utf8');
        await expect(fs.stat(path.dirname(input))).rejects.toMatchObject({ code: 'ENOENT' });
    } finally {
        await fs.rm(directory, { recursive: true, force: true });
    }
});

test('process and protocol failures reach the caller', async () => {
    await expect(runHighlighter({ executable: '/no/such/crust-highlighter', text: '' })).rejects.toThrow();
    await expect(runHighlighter({ executable: 'python3', args: ['-c', 'import sys;sys.stderr.write("bad profile");sys.exit(3)'], text: '' })).rejects.toThrow('bad profile');
    await expect(runHighlighter({ executable: 'python3', args: ['-c', 'print("not json")'], text: '' })).rejects.toThrow();
    await expect(runHighlighter({ executable: 'python3', args: ['-c', 'import sys;sys.stderr.write("x"*65537)'], text: '' })).rejects.toThrow('64 KiB');
});

test('JSON output is bounded before parsing and the native producer bounds dense tokens', async () => {
    const padded = 'import sys;value=sys.argv[1];sys.stdout.write(value+" "*(8*1024*1024-len(value)))';
    const exact = await runHighlighter({
        executable: 'python3', args: ['-c', padded, JSON.stringify(response('', []))], text: '',
    });
    expect(decodeTokens(exact, '').data.length).toBe(0);
    const script = 'import sys;sys.stdout.write(" "*(8*1024*1024+1))';
    await expect(runHighlighter({ executable: 'python3', args: ['-c', script], text: '' })).rejects.toThrow('8 MiB');
    await expect(runHighlighter({ executable, text: ';x'.repeat(250001) })).rejects.toThrow('highlight span limit exceeded');
});
