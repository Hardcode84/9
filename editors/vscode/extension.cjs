// SPDX-License-Identifier: Apache-2.0

'use strict';

const vscode = require('vscode');
const path = require('node:path');
const { tokenTypes, tokenModifiers, decodeTokens, runHighlighter } = require('./adapter.cjs');

function activate(context) {
    const legend = new vscode.SemanticTokensLegend(tokenTypes, tokenModifiers);
    const changed = new vscode.EventEmitter();
    const diagnostics = vscode.languages.createDiagnosticCollection('crust-highlight');
    const output = vscode.window.createOutputChannel('Crust highlighting');
    const requests = new Map();
    const cancelAll = () => { for (const request of requests.values()) request.abort(); };
    const refresh = () => { cancelAll(); changed.fire(); };
    const provider = {
        onDidChangeSemanticTokens: changed.event,
        async provideDocumentSemanticTokens(document, cancellation) {
            const key = document.uri.toString();
            requests.get(key)?.abort();
            const controller = new AbortController();
            requests.set(key, controller);
            const subscription = cancellation.onCancellationRequested(() => controller.abort());
            if (cancellation.isCancellationRequested) controller.abort();
            const version = document.version;
            const text = document.getText();
            try {
                const config = vscode.workspace.getConfiguration('crust', document.uri);
                const configured = vscode.workspace.isTrusted ? config.get('highlighter.path', '') : '';
                let executable = path.join(context.extensionPath, 'bin', 'crust-highlight');
                let args = [];
                if (configured) {
                    if (typeof configured !== 'string') throw new Error('Highlighter path must be a string');
                    executable = configured;
                    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
                    const expand = argument => {
                        if (typeof argument !== 'string') throw new Error('Highlighter arguments must be strings');
                        if (!argument.includes('${workspaceFolder}')) return argument;
                        if (!folder) throw new Error('workspaceFolder requires a workspace folder');
                        return argument.replaceAll('${workspaceFolder}', folder.uri.fsPath);
                    };
                    executable = expand(executable);
                    if (!path.isAbsolute(executable) && (executable.includes('/') || executable.includes('\\'))) {
                        if (!folder) throw new Error('A relative highlighter path requires a workspace folder');
                        executable = path.resolve(folder.uri.fsPath, executable);
                    }
                    args = config.get('highlighter.arguments', []);
                    if (!Array.isArray(args)) throw new Error('Highlighter arguments must be an array');
                    args = args.map(expand);
                }
                const response = await runHighlighter({
                    executable, args, text, signal: controller.signal,
                    timeoutMs: config.get('highlighter.timeoutMs', 5000),
                });
                if (controller.signal.aborted || document.version !== version || document.isClosed) throw new vscode.CancellationError();
                const tokens = decodeTokens(response, text);
                diagnostics.set(document.uri, tokens.issues.map(issue => new vscode.Diagnostic(
                    new vscode.Range(issue.line, issue.start, issue.line, issue.end),
                    issue.kind === 10 ? 'Invalid token in the selected highlighting grammar.' :
                        'The selected highlighting service could not resolve this region.',
                    issue.kind === 10 ? vscode.DiagnosticSeverity.Error : vscode.DiagnosticSeverity.Warning,
                )));
                return new vscode.SemanticTokens(tokens.data);
            } catch (error) {
                if (controller.signal.aborted || document.version !== version || document.isClosed) throw new vscode.CancellationError();
                const message = `Crust highlighting: ${error.message}`;
                output.appendLine(message);
                diagnostics.set(document.uri, [new vscode.Diagnostic(
                    new vscode.Range(0, 0, 0, 0), message, vscode.DiagnosticSeverity.Warning,
                )]);
                throw error;
            } finally {
                subscription.dispose();
                if (requests.get(key) === controller) requests.delete(key);
            }
        },
    };
    context.subscriptions.push(changed, diagnostics, output,
        vscode.languages.registerDocumentSemanticTokensProvider({ language: 'crust' }, provider, legend),
        vscode.workspace.onDidChangeConfiguration(event => { if (event.affectsConfiguration('crust')) refresh(); }),
        vscode.workspace.onDidGrantWorkspaceTrust(refresh),
        vscode.workspace.onDidCloseTextDocument(document => {
            requests.get(document.uri.toString())?.abort();
            diagnostics.delete(document.uri);
        }),
        { dispose: cancelAll },
    );
}

module.exports = { activate };
