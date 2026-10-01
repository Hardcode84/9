"""Check Python file, interactive input, and import boundaries; print JSON."""

from pathlib import Path
import code
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile


def check_boundaries(work):
    observations = []

    def observe(name, condition, **details):
        if not condition:
            raise AssertionError((name, details))
        observations.append({"name": name, "passed": True, **details})

    def run_file(name, body):
        source = work / (name + ".py")
        marker = work / (name + ".marker")
        source.write_text(body, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(source), str(marker)],
            capture_output=True, text=True, check=False,
        )
        return result, marker.exists()

    preamble = (
        "from pathlib import Path\nimport sys\n"
        'Path(sys.argv[1]).write_text("early")\n'
    )
    result, exists = run_file("later_syntax_error", preamble + "if:\n    pass\n")
    observe(
        "file: later syntax error prevents first side effect",
        result.returncode != 0 and "SyntaxError" in result.stderr and not exists,
        status=result.returncode, marker=exists,
    )
    result, exists = run_file(
        "function_body_syntax_error",
        preamble + "def unused():\n    if:\n        pass\n",
    )
    observe(
        "file: syntax error in unused body prevents first side effect",
        result.returncode != 0 and "SyntaxError" in result.stderr and not exists,
        status=result.returncode, marker=exists,
    )
    result, exists = run_file("later_runtime_error", preamble + "undefined_name\n")
    observe(
        "file: later runtime error retains earlier side effect",
        result.returncode != 0 and "NameError" in result.stderr and exists,
        status=result.returncode, marker=exists,
    )

    events = []
    try:
        exec("events.append('early')\nif:\n    pass\n", {"events": events})
    except SyntaxError:
        caught = True
    else:
        caught = False
    observe("exec string: parse before execution", caught and not events,
            events=events)

    events = []
    console = code.InteractiveConsole({"events": events})
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        first = console.push("events.append('early')")
        second = console.push("if:")
    observe(
        "interactive: a later invalid unit retains the prior unit effect",
        first is False and second is False and events == ["early"]
        and "SyntaxError" in errors.getvalue(),
        events=events, incomplete=[first, second],
    )

    events = []
    console = code.InteractiveConsole({"events": events})
    first = console.push("if True:")
    second = console.push("    events.append('body')")
    observe(
        "interactive: incomplete compound unit does not execute",
        first is True and second is True and not events, events=list(events),
    )
    third = console.push("")
    observe(
        "interactive: complete compound unit executes once",
        third is False and events == ["body"], events=list(events),
    )

    (work / "answer.toy").write_text("answer => 42!\n", encoding="utf-8")
    loader_source = '''from pathlib import Path
import importlib.abc
import importlib.util
import sys

class Loader(importlib.abc.Loader):
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        text = Path(__file__).with_name('answer.toy').read_text()
        prefix, number = text.rstrip().split(' => ')
        assert prefix == 'answer' and number.endswith('!')
        module.answer = int(number[:-1])
        Path(sys.argv[1]).write_text('loaded')

class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'custom_answer':
            return importlib.util.spec_from_loader(fullname, Loader())
        return None

sys.meta_path.insert(0, Finder())
import custom_answer
assert custom_answer.answer == 42
'''
    result, exists = run_file("custom_import_loader", loader_source)
    observe(
        "import hook: earlier execution can interpret a later imported input",
        result.returncode == 0 and exists, status=result.returncode, marker=exists,
    )
    result, exists = run_file(
        "hook_then_current_file_invalid", loader_source + "\nanswer => 42!\n",
    )
    observe(
        "import hook: cannot repair later invalid syntax in its current file",
        result.returncode != 0 and "SyntaxError" in result.stderr and not exists,
        status=result.returncode, marker=exists,
    )
    return observations


def main():
    with tempfile.TemporaryDirectory(prefix="crust-python-order-") as directory:
        observations = check_boundaries(Path(directory))
    report = {
        "python": sys.version,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "count": len(observations),
        "observations": observations,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
