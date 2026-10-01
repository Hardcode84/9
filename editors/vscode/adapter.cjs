// SPDX-License-Identifier: Apache-2.0

'use strict';

const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const tokenTypes = [
    'keyword', 'comment', 'string', 'number', 'operator', 'type',
    'variable', 'function', 'struct', 'property', 'invalid', 'unresolved',
];
const tokenModifiers = ['declaration', 'readonly'];
const maxSourceBytes = 4 * 1024 * 1024;
const maxOutputBytes = 8 * 1024 * 1024;
const maxTokenCount = 500000;

function snapshot(text) {
    if (text.length > maxSourceBytes) {
        throw new Error('Highlight input exceeds the 4 MiB editor limit');
    }
    for (let index = 0; index < text.length; index++) {
        const code = text.charCodeAt(index);
        if (code >= 0xd800 && code <= 0xdbff) {
            const next = text.charCodeAt(++index);
            if (!(next >= 0xdc00 && next <= 0xdfff)) {
                throw new Error('Document contains an unpaired UTF-16 surrogate');
            }
        } else if (code >= 0xdc00 && code <= 0xdfff) {
            throw new Error('Document contains an unpaired UTF-16 surrogate');
        }
    }
    const bytes = Buffer.from(text, 'utf8');
    if (bytes.length > maxSourceBytes) {
        throw new Error('Highlight input exceeds the 4 MiB editor limit');
    }
    return bytes;
}

function sameLegend(actual, expected) {
    return Array.isArray(actual) && actual.length === expected.length &&
        actual.every((name, index) => name === expected[index]);
}

// Validate the process response and convert byte ranges against this exact snapshot.
function decodeTokens(response, text) {
    const byteLength = snapshot(text).length;
    if (!response || response.version !== 1 || response.byteLength !== byteLength ||
        !sameLegend(response.tokenTypes, tokenTypes) ||
        !sameLegend(response.tokenModifiers, tokenModifiers) || !Array.isArray(response.spans)) {
        throw new Error('Invalid Crust highlight response or legend');
    }
    if (response.spans.length > maxTokenCount) {
        throw new Error('Highlight response exceeds the 500000 span limit');
    }
    let data = new Uint32Array(response.spans.length * 5);
    let used = 0;
    const issues = new Map();
    let byte = 0, index = 0, line = 0, column = 0;
    let previousLine = 0, previousColumn = 0, previousEnd = 0;

    function emit(startLine, startColumn, endColumn, kind, modifiers) {
        if (startColumn === endColumn) return;
        if (used === maxTokenCount * 5) {
            throw new Error('Highlight result exceeds the 500000 semantic token limit');
        }
        if (used === data.length) {
            const grown = new Uint32Array(Math.min(maxTokenCount * 5, Math.max(5, data.length * 2)));
            grown.set(data);
            data = grown;
        }
        data[used++] = startLine - previousLine;
        data[used++] = startLine === previousLine ? startColumn - previousColumn : startColumn;
        data[used++] = endColumn - startColumn;
        data[used++] = kind;
        data[used++] = modifiers;
        previousLine = startLine;
        previousColumn = startColumn;
        if (kind >= 10 && !issues.has(kind)) {
            issues.set(kind, { line: startLine, start: startColumn, end: endColumn, kind });
        }
    }

    function advance(target, kind, modifiers) {
        let startLine = line, startColumn = column;
        while (byte < target) {
            const code = text.codePointAt(index);
            const width = code > 0xffff ? 2 : 1;
            const size = code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4;
            if (byte + size > target) throw new Error('Highlight span splits a UTF-8 character');
            if (code === 10 || code === 13) {
                if (kind !== undefined) emit(startLine, startColumn, column, kind, modifiers);
                if (code === 13 || index === 0 || text.charCodeAt(index - 1) !== 13) line++;
                column = 0;
                startLine = line;
                startColumn = 0;
            } else {
                column += width;
            }
            byte += size;
            index += width;
        }
        if (kind !== undefined) emit(startLine, startColumn, column, kind, modifiers);
    }

    for (const span of response.spans) {
        if (!Array.isArray(span) || span.length !== 4 ||
            !span.every(value => Number.isSafeInteger(value) && value >= 0)) {
            throw new Error('Invalid highlight span fields');
        }
        const [begin, end, kind, modifiers] = span;
        if (begin < previousEnd || begin >= end || end > byteLength ||
            kind >= tokenTypes.length || modifiers > 3) {
            throw new Error('Invalid highlight span range or classification');
        }
        advance(begin);
        const issueStart = kind >= 10 && !issues.has(kind) ? { line, start: column, end: column, kind } : undefined;
        advance(end, kind, modifiers);
        if (issueStart && !issues.has(kind)) issues.set(kind, issueStart);
        previousEnd = end;
    }
    return { data: data.subarray(0, used), issues: [...issues.values()] };
}

async function runHighlighter({ executable, args = [], text, signal, timeoutMs = 5000 }) {
    const bytes = snapshot(text);
    if (signal?.aborted) throw new Error('Highlight request cancelled');
    if (typeof executable !== 'string' || !executable || !Array.isArray(args) ||
        !args.every(arg => typeof arg === 'string') ||
        !Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 60000) {
        throw new Error('Invalid Crust highlighter configuration');
    }
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'crust-highlight-'));
    try {
        const input = path.join(directory, 'snapshot.crs');
        await fs.writeFile(input, bytes, { mode: 0o600 });
        if (signal?.aborted) throw new Error('Highlight request cancelled');
        const output = await new Promise((resolve, reject) => {
            const child = spawn(executable, [...args, '--tokens', input], {
                cwd: directory, stdio: ['ignore', 'pipe', 'pipe'], shell: false, windowsHide: true,
            });
            const chunks = [], errors = [];
            let size = 0, errorSize = 0, failure;
            const stop = error => {
                if (!failure) failure = error;
                child.kill('SIGKILL');
                child.stdout.destroy();
                child.stderr.destroy();
            };
            const cancel = () => stop(new Error('Highlight request cancelled'));
            signal?.addEventListener('abort', cancel, { once: true });
            const timer = setTimeout(() => stop(new Error('Crust highlighter timed out')), timeoutMs);
            child.stdout.on('data', chunk => {
                size += chunk.length;
                if (size > maxOutputBytes) stop(new Error('Highlight output exceeds 8 MiB'));
                else if (!failure) chunks.push(chunk);
            });
            child.stderr.on('data', chunk => {
                errorSize += chunk.length;
                if (errorSize > 65536) stop(new Error('Highlighter diagnostic exceeds 64 KiB'));
                else if (!failure) errors.push(chunk);
            });
            child.on('error', error => { failure = error; });
            child.on('close', (code, termination) => {
                clearTimeout(timer);
                signal?.removeEventListener('abort', cancel);
                if (failure) reject(failure);
                else if (code !== 0) {
                    const message = Buffer.concat(errors).toString('utf8').trim();
                    reject(new Error(`Highlighter exited with ${termination || code}${message ? ': ' + message : ''}`));
                } else if (errorSize !== 0) {
                    reject(new Error(`Highlighter diagnostic: ${Buffer.concat(errors).toString('utf8').trim()}`));
                } else resolve(Buffer.concat(chunks).toString('utf8'));
            });
            if (signal?.aborted) cancel();
        });
        return JSON.parse(output);
    } finally {
        await fs.rm(directory, { recursive: true, force: true });
    }
}

module.exports = { tokenTypes, tokenModifiers, snapshot, decodeTokens, runHighlighter };
