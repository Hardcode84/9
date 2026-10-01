#!/usr/bin/env python3
"""Measure the bounded source-order proof; this is not a full evaluator."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import statistics
import subprocess

ROOT = Path.cwd()
HERE = Path(os.environ.get('RMD_PROOF_DIR', ROOT / '.profile-cache/source-order-proof-replay'))
BUILD = Path(os.environ.get('RMD_PROOF_BUILD', ROOT / 'build'))
SPEC = importlib.util.spec_from_file_location('bootstrap_measure', ROOT / 'benchmarks/bootstrap/measure.py')
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
os.sched_setaffinity(0, {4})

def info(path):
    path = Path(path)
    data = path.read_bytes()
    return {'path': str(path), 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def checked(command):
    result = BASE.run_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode or result.stderr:
        raise RuntimeError((command, result.returncode, result.stderr))
    return result.stdout

interfaces = [ROOT / p for p in ('api/rmd0.rmd', 'api/rmd0_stage.rmd', 'stages/c/api.rmd')]
interfaces += [HERE / 'model.rmd', HERE / 'interface.rmd']

def proof_command(source):
    result = [str(HERE / 'runner'), str(source)]
    for path in interfaces:
        result += ['--api', str(path)]
    result += ['--load', str(HERE / 'reader.plugin'), '--load', str(HERE / 'output.plugin')]
    return result + ['--', '/dev/null']

commands = {
    'source-order-output': proof_command(HERE / 'main.rmd'),
    'fixed-reader-output': proof_command(HERE / 'native-no-reader-change.rmd'),
    'prepared-output': [str(BUILD / 'rmd-c'), '--emit-c', '--symbols', '/dev/null', str(ROOT / 'examples/intrusive.rmd')],
    'gcc-original-syntax': ['gcc', '-std=c99', '-pedantic-errors', '-O0', '-g0', '-fsyntax-only', '-Iinclude', 'benchmarks/bootstrap/intrusive.c'],
}
paths = [HERE / p for p in ('runner', 'reader.plugin', 'output.plugin', 'runner.c', 'proof.h', 'model.rmd', 'interface.rmd', 'plugin.rmd', 'main.rmd', 'native-no-reader-change.rmd', 'verify.py', 'verification.json', 'measure.py')]
paths += [BUILD / p for p in ('rmd-c','rmd-c-library.so','librmd0_host.a')]
paths += [HERE / 'replay-build.json']
paths += interfaces + [ROOT / p for p in ( 'examples/intrusive.rmd', 'benchmarks/bootstrap/intrusive.c', 'benchmarks/bootstrap/measure.py')]
paths += [BUILD / p for p in ('core.o', 'read.o', 'check.o', 'host.o')]
paths += sorted((ROOT / 'src').glob('*.c')) + sorted((ROOT / 'include').glob('*.h')) + sorted((ROOT / 'stages/c').glob('*.rmd'))
hashes = {str(path): info(path) for path in paths}
if info(HERE / 'output.plugin')['sha256'] != info(BUILD / 'rmd-c-library.so')['sha256']:
    raise RuntimeError('Ordinary backend copy differs from prepared input')
if json.loads((HERE/'verification.json').read_text())['status'] != 'passed':
    raise RuntimeError('Correctness gate missing')
expected = (HERE/'reference.c').read_bytes()
for endpoint in ('source-order-output', 'fixed-reader-output', 'prepared-output'):
    if checked(commands[endpoint]) != expected:
        raise RuntimeError('Generated output differs: '+endpoint)
if checked([str(HERE/'target')]) != b'intrusive: ok\n':
    raise RuntimeError('Target output differs')
result = {
    'status': 'running', 'cpu': 4, 'rounds': 25, 'warmup_rounds': 1, 'bootstrap_draws': 10000,
    'seed': 202610015, 'environment': BASE.environment(4),
    'tools': {name: BASE.tool_info(name) for name in ('gcc', 'as', 'ld', 'objcopy', 'nm', 'readelf')},
    'libffi_version': checked(['pkg-config','--modversion','libffi']).decode().strip(),
    'runner_shared_libraries': BASE.shared_libraries(HERE/'runner'), 'input_artifacts': hashes,
    'commands': commands, 'warmups': [], 'samples': [],
    'replay_build': json.loads((HERE / 'replay-build.json').read_text()),
    'scope': {
        'source-order-output': 'Fresh process; interface source IO/read/collect/resolve/check; root IO; ordinary initial call parse/check; dlopen/dlsym and libffi call preparation/execution; reader switch before hostile NUL; RMD alternate reader; checked actions; target source IO/read/check; complete C and rename output; destruction with RMD callbacks; dlclose.',
        'fixed-reader-output': 'Same executor, interfaces, libraries, target, and output; ordinary initial reader handles all root actions without grammar change.',
        'prepared-output': 'Prepared standalone native C backend; actual target frontend/full C and rename output.',
        'gcc-original-syntax': 'Matched original C preprocessing and semantic checking.',
        'included_setup': 'All per-invocation host interface parsing, checking, module loading, ffi preparation, root execution and cleanup. No as/ld or per-form subprocess occurs.',
        'excluded': 'Prepared runner and explicit reader/backend library builds; final generated-target GCC/objcopy/link; correctness preflight.',
        'cold_definition': 'New process, module load and call preparation per invocation; filesystem caches are warm.',
        'not_established': 'Full RMD host evaluation, root variables/declarations/control flow, interpreted callbacks/closures, arbitrary action representations, or full runner speed.',
    },
}
BASE.save(HERE/'result.json', result)
for endpoint, command in commands.items():
    result['warmups'].append({'endpoint':endpoint, 'wall_ns':BASE.measure(command)})
rng = random.Random(result['seed'])
for index in range(result['rounds']):
    order = list(commands); rng.shuffle(order)
    for endpoint in order:
        result['samples'].append({'round':index,'endpoint':endpoint,'sequence':len(result['samples']), 'wall_ns':BASE.measure(commands[endpoint])})
for path, expected_info in hashes.items():
    if info(path) != expected_info:
        raise RuntimeError('Input changed during measurement: '+path)
paired = [{r['endpoint']:r['wall_ns'] for r in result['samples'] if r['round']==index} for index in range(result['rounds'])]
medians = {name: statistics.median(row[name] for row in paired) for name in commands}
summary = {'median_ms':{name:value/1e6 for name,value in medians.items()},'comparisons':{}}
for numerator,denominator in [('source-order-output','gcc-original-syntax'),('source-order-output','prepared-output'),('source-order-output','fixed-reader-output')]:
    prng=random.Random(str(result['seed'])+numerator+denominator)
    ratios=[]; differences=[]
    for _ in range(result['bootstrap_draws']):
        sample=prng.choices(paired,k=len(paired))
        ratios.append(statistics.median(r[numerator] for r in sample)/statistics.median(r[denominator] for r in sample))
        differences.append(statistics.median(r[numerator]-r[denominator] for r in sample)/1e6)
    ratios.sort(); differences.sort()
    summary['comparisons'][numerator+'/'+denominator]={
        'ratio_of_medians':medians[numerator]/medians[denominator],
        'paired_bootstrap_ratio_95_ci':[BASE.percentile(ratios,.025),BASE.percentile(ratios,.975)],
        'median_of_paired_ratios':statistics.median(r[numerator]/r[denominator] for r in paired),
        'median_paired_difference_ms':statistics.median(r[numerator]-r[denominator] for r in paired)/1e6,
        'paired_difference_95_ci_ms':[BASE.percentile(differences,.025),BASE.percentile(differences,.975)],
    }
summary['first_gate_passed']=summary['comparisons']['source-order-output/gcc-original-syntax']['paired_bootstrap_ratio_95_ci'][1] <= 1
result['summary']=summary;result['status']='complete'
BASE.save(HERE/'result.json',result)
print(json.dumps(summary,indent=2))
