// SPDX-License-Identifier: Apache-2.0

import { test, expect, mock } from 'bun:test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const launcher = process.env.CRUST_LAUNCHER;
if (!launcher) throw new Error('Run make check-vscode to supply the source launcher');

const state = { trusted: true, config: {}, providers: [], diagnostics: new Map(), messages: [] };
const disposable = () => ({ dispose() {} });
class EventEmitter {
    constructor() {
        this.listeners = new Set();
        this.event = listener => { this.listeners.add(listener); return { dispose: () => this.listeners.delete(listener) }; };
    }
    fire(value) { for (const listener of this.listeners) listener(value); }
    dispose() { this.listeners.clear(); }
}
class Range { constructor(line, start, endLine, end) { Object.assign(this, { line, start, endLine, end }); } }
mock.module('vscode', () => ({
    EventEmitter, Range,
    SemanticTokensLegend: class { constructor(types, modifiers) { Object.assign(this, { types, modifiers }); } },
    SemanticTokens: class { constructor(data) { this.data = data; } },
    Diagnostic: class { constructor(range, message, severity) { Object.assign(this, { range, message, severity }); } },
    DiagnosticSeverity: { Error: 0, Warning: 1 },
    languages: {
        createDiagnosticCollection: () => ({
            set: (uri, values) => state.diagnostics.set(uri.toString(), values),
            delete: uri => state.diagnostics.delete(uri.toString()), dispose() {},
        }),
        registerDocumentSemanticTokensProvider: (selector, provider) => { state.providers.push(provider); return disposable(); },
    },
    window: { createOutputChannel: () => ({ appendLine: message => state.messages.push(message), dispose() {} }) },
    workspace: {
        get isTrusted() { return state.trusted; },
        getConfiguration: () => ({ get: (name, initial) => state.config[name] ?? initial }),
        getWorkspaceFolder: () => ({ uri: { fsPath: process.cwd() } }),
        onDidChangeConfiguration: disposable, onDidGrantWorkspaceTrust: disposable, onDidCloseTextDocument: disposable,
    },
}));
const { activate } = await import('./extension.cjs');

test('provider publishes current tokens, discards stale snapshots, and gates custom execution', async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'crust-extension-test-'));
    const context = { extensionPath: directory, subscriptions: [] };
    await fs.mkdir(path.join(directory, 'bin'));
    await fs.symlink(process.env.CRUST_HIGHLIGHT, path.join(directory, 'bin', 'crust-highlight'));
    const changed = new EventEmitter();
    const cancellation = { isCancellationRequested: false, onCancellationRequested: changed.event };
    const document = { uri: { toString: () => 'untitled:unsaved.crs' }, version: 1, isClosed: false, getText: () => 'fn draft()->unit{}' };
    try {
        activate(context);
        const provider = state.providers.at(-1);
        state.config = { 'highlighter.path': '/must/not/execute/workspace-code' };
        state.trusted = false;
        expect((await provider.provideDocumentSemanticTokens(document, cancellation)).data.length).toBeGreaterThan(0);
        const pending = provider.provideDocumentSemanticTokens(document, cancellation);
        document.version++;
        expect(await pending).toBeUndefined();
        const cancelled = provider.provideDocumentSemanticTokens(document, cancellation);
        changed.fire();
        expect(await cancelled).toBeUndefined();
        state.trusted = true;
        state.config = {
            'highlighter.path': '${workspaceFolder}/' + path.relative(process.cwd(), launcher),
            'highlighter.arguments': ['${workspaceFolder}/examples/highlight/reader-switch.crs'],
        };
        const readerText = await fs.readFile(path.join(process.cwd(), 'examples/reader-switch/main.crs'), 'utf8');
        document.getText = () => readerText;
        expect((await provider.provideDocumentSemanticTokens(document, cancellation)).data.length).toBeGreaterThan(0);
        expect(state.diagnostics.get(document.uri.toString())).toEqual([]);
        state.config = { 'highlighter.path': '/must/not/execute/workspace-code' };
        await expect(provider.provideDocumentSemanticTokens(document, cancellation)).rejects.toThrow();
        expect(state.diagnostics.get(document.uri.toString())[0].message).toContain('Crust highlighting:');
        expect(state.messages.length).toBe(1);
    } finally {
        for (const item of context.subscriptions) item.dispose();
        await fs.rm(directory, { recursive: true, force: true });
    }
});
