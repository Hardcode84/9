// SPDX-License-Identifier: Apache-2.0

'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const { runHighlighter, decodeTokens } = require('../editors/vscode/adapter.cjs');

async function main() {
    const [executable, repository] = process.argv.slice(2);
    const text = '// 雪\nfn answer()->i32{return 42i32;}\n';
    const options = {
        executable, text, timeoutMs: 30000,
        args: [path.join(repository, 'stages/build/run.crs'), 'stages/highlight/tool.crs'],
    };
    const response = await runHighlighter(options);
    const decoded = decodeTokens(response, text);
    assert(response.spans.length > 0);
    assert(decoded.data.length > 0);
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(runHighlighter({ ...options, signal: controller.signal }), /cancelled/);
    await assert.rejects(runHighlighter({ ...options, executable: executable + '.missing' }));
    console.log('Windows editor native launch, UTF-8 tokens, cancellation, and failure passed');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
