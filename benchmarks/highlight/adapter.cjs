'use strict';

const fs = require('node:fs');
const { performance } = require('node:perf_hooks');
const { runHighlighter, decodeTokens } = require('../../editors/vscode/adapter.cjs');

async function main() {
    const [executable, input, rounds] = process.argv.slice(2);
    const text = fs.readFileSync(input, 'utf8');
    const samples = [];
    for (let index = 0; index < Number(rounds); index++) {
        const start = performance.now();
        const response = await runHighlighter({ executable, text });
        const received = performance.now();
        decodeTokens(response, text);
        samples.push({ process_transport_json_ms: received - start, conversion_ms: performance.now() - received });
    }
    process.stdout.write(JSON.stringify(samples));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
