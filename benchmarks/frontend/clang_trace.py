#!/usr/bin/env python3
"""Report elapsed time from one raw Clang frontend time trace.

The trace must contain one ExecuteCompiler scope on one real thread.
Source scopes must use adjacent LLVM begin/end records. Unknown event phases,
crossing complete scopes, and scopes outside the boundary cause an error.
Output describes the instrumented run. It does not estimate normal run time.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


class TraceError(ValueError):
    """The trace does not meet the accepted input conditions."""


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    index: int
    name: str
    pid: int
    tid: int

    @property
    def duration(self):
        return self.end - self.start


def integer(event, key):
    value = event.get(key)
    if type(value) is not int or value < 0:
        raise TraceError(f"Expected a nonnegative integer for {key}: {event}")
    return value


def span(event, index, end=None):
    name = event.get("name")
    if not isinstance(name, str) or not name:
        raise TraceError(f"Missing event name at event {index}")
    start = integer(event, "ts")
    if end is None:
        end = start + integer(event, "dur")
    if end < start:
        raise TraceError(f"Negative event duration at event {index}")
    return Span(start, end, index, name, integer(event, "pid"),
                integer(event, "tid"))


def union(spans):
    result = []
    for start, end in sorted((s.start, s.end) for s in spans if s.duration):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def duration(intervals):
    return sum(end - start for start, end in intervals)


def intersection_duration(left, right):
    total = i = j = 0
    while i < len(left) and j < len(right):
        total += max(0, min(left[i][1], right[j][1])
                     - max(left[i][0], right[j][0]))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return total


def category(name):
    if name in ("InstantiateClass", "InstantiateFunction"):
        return "template_scope_self"
    if name.startswith("Parse"):
        return "parse_scope_self"
    if name.startswith("Evaluate") or name in (
            "isIntegerConstantExpr", "isPotentialConstantExpr"):
        return "constant_evaluation_scope_self"
    if name == "PerformPendingInstantiations":
        return "pending_instantiation_scope_self"
    if name == "Frontend":
        return "frontend_residual"
    if name == "ExecuteCompiler":
        return "compiler_action_residual"
    return "other_named_X_scope_self"


def analyze(document):
    if not isinstance(document, dict):
        raise TraceError("Expected a JSON object")
    events = document.get("traceEvents")
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        raise TraceError("Expected a traceEvents array of event objects")
    complete, headers, summaries = [], [], {}
    summary_counts = {}
    phase_counts = Counter()
    index = 0
    while index < len(events):
        event = events[index]
        phase = event.get("ph")
        phase_counts[phase] += 1
        if phase == "X":
            item = span(event, index)
            if item.name.startswith("Total "):
                if item.name in summaries:
                    raise TraceError(f"Duplicate summary: {item.name}")
                summaries[item.name] = item.duration
                summary_counts[item.name] = event.get("args", {}).get("count")
            elif item.name == "Source":
                raise TraceError("X Source events are not supported; expected LLVM b/e pairs")
            else:
                complete.append(item)
        elif phase == "b":
            if event.get("name") != "Source" or index + 1 == len(events):
                raise TraceError(f"Unsupported async begin at event {index}")
            ending = events[index + 1]
            fields = ("name", "pid", "tid", "cat", "id")
            if (ending.get("ph") != "e" or "id" not in event
                    or any(event.get(k) != ending.get(k) for k in fields)):
                raise TraceError(f"Expected an adjacent matching Source end after event {index}")
            headers.append(span(event, index, integer(ending, "ts")))
            phase_counts["e"] += 1
            index += 1
        elif phase not in ("M", "i"):
            raise TraceError(f"Unsupported or unmatched event phase {phase!r} at event {index}")
        index += 1

    roots = [s for s in complete if s.name == "ExecuteCompiler"]
    if len(roots) != 1 or roots[0].duration <= 0:
        raise TraceError("Expected exactly one positive ExecuteCompiler scope")
    root = roots[0]
    for item in complete + headers:
        if (item.pid, item.tid) != (root.pid, root.tid):
            raise TraceError(f"Multiple real processes or threads: event {item.index}")
        if item.start < root.start or item.end > root.end:
            raise TraceError(f"Scope outside ExecuteCompiler: event {item.index} ({item.name})")

    positive = sorted((s for s in complete if s.duration),
                      key=lambda s: (s.start, -s.end, -s.index))
    if positive[0] != root:
        raise TraceError("ExecuteCompiler is not the outer complete scope")
    self_us = {s.index: s.duration for s in complete}
    stack = []
    for item in positive:
        while stack and item.start >= stack[-1].end:
            stack.pop()
        if stack:
            parent = stack[-1]
            if item.end > parent.end:
                raise TraceError(f"Crossing complete scopes: events {parent.index} and {item.index}")
            self_us[parent.index] -= item.duration
        elif item != root:
            raise TraceError(f"Complete scope has no parent: event {item.index}")
        stack.append(item)
    if min(self_us.values()) < 0 or sum(self_us.values()) != root.duration:
        raise TraceError("Complete-scope self time does not partition ExecuteCompiler")

    by_name = defaultdict(lambda: {"count": 0, "zero_duration_count": 0, "self_us": 0})
    spans_by_name = defaultdict(list)
    categories = Counter()
    for item in complete:
        spans_by_name[item.name].append(item)
        entry = by_name[item.name]
        entry["count"] += 1
        entry["zero_duration_count"] += item.duration == 0
        entry["self_us"] += self_us[item.index]
        categories[category(item.name)] += self_us[item.index]
    for name, spans in spans_by_name.items():
        by_name[name]["inclusive_union_us"] = duration(union(spans))

    template_names = ("InstantiateClass", "InstantiateFunction")
    template_union = union(s for s in complete if s.name in template_names)
    header_union = union(headers)
    template_us, header_us = duration(template_union), duration(header_union)
    overlap_us = intersection_duration(template_union, header_union)
    partition = {
        "header_and_template": overlap_us,
        "header_without_template": header_us - overlap_us,
        "template_outside_header": template_us - overlap_us,
        "neither_header_nor_template": root.duration - header_us - template_us + overlap_us,
    }
    if min(partition.values()) < 0 or sum(partition.values()) != root.duration:
        raise TraceError("Header/template partition does not cover ExecuteCompiler")

    return {
        "schema": "clang-frontend-trace-v1",
        "unit": "microseconds",
        "boundary": {"name": root.name, "pid": root.pid, "tid": root.tid,
                     "start_us": root.start, "end_us": root.end,
                     "instrumented_duration_us": root.duration},
        "event_phase_counts": dict(phase_counts),
        "complete_scope_count": len(complete),
        "source_scope_count": len(headers),
        "source_scopes_observed": bool(headers),
        "self_time_by_X_name": [dict(name=name, **entry) for name, entry in
                                sorted(by_name.items(), key=lambda pair: (-pair[1]["self_us"], pair[0]))],
        "disjoint_X_categories_us": dict(categories),
        "inclusive_interval_union_us": {
            "template_scopes": template_us,
            **{name: duration(union(s for s in complete if s.name == name))
               for name in template_names},
            "header_source_scopes": header_us,
        },
        "disjoint_header_template_partition_us": partition,
        "excluded_summary_durations_us": summaries,
        "excluded_summary_counts": summary_counts,
        "notes": [
            "These are elapsed times from an instrumented run, not estimates of normal phase costs.",
            "Each disjoint table separately sums to ExecuteCompiler. Do not add the tables together.",
            "X self time excludes nested X time. Equal spans use LLVM completion order to select the parent.",
            "Source b/e spans are header overlays. They do not subtract from X self time.",
            "Header time includes work while a header is active, including parsing and semantic work.",
            "Template scopes include only InstantiateClass and InstantiateFunction, not every template-related operation.",
            "Parse scope self time is a timer location, not pure grammar recognition.",
            "Residual scope time includes uninstrumented work and profiler overhead within that scope.",
            "Total summary events, metadata, and instantaneous events do not contribute time.",
            "Per-name inclusive unions overlap other names. Summary counts can omit nested occurrences of the same name.",
            "An absent Source scope means no header interval was observed; it does not establish zero header cost.",
            "The trace does not record its granularity. Omitted short scopes remain in their enclosing scope's self time.",
            "The boundary excludes driver startup, trace serialization, and other work outside ExecuteCompiler.",
            "The recorded compiler command must establish the syntax-only boundary; this trace does not record those flags.",
            "This reader accepts one real thread and raw adjacent LLVM Source pairs; it rejects unsupported layouts.",
        ],
    }


def analyze_trace(path):
    """Return the elapsed-time report for a raw trace file.

    Raise TraceError for unsupported event data. Raise OSError if the file
    cannot be read. The result includes the input path and its SHA-256 hash.
    """
    path = Path(path)
    data = path.read_bytes()
    result = analyze(json.loads(data))
    result["input"] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, help="Write to a new JSON file instead of stdout")
    args = parser.parse_args()
    try:
        result = analyze_trace(args.trace)
        output = json.dumps(result, indent=2) + "\n"
        if args.output:
            with args.output.open("x") as destination:
                destination.write(output)
        else:
            print(output, end="")
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
