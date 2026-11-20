"""Deterministic BlenderMCP-Bench runner.

Run inside Blender:
    blender -b --factory-startup --python bench/runner.py -- --runs 1

The runner clears the scene before each task, executes the action, compares the
observed result with expected.json, saves a .blend and writes metrics.json and
trace.jsonl. It does not call an LLM and does not compare against other
servers; see bench/README.md for the external-comparison protocol.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pro"))
sys.path.insert(0, str(ROOT / "bench"))

import actions  # noqa: E402
import bpy  # noqa: E402

from blender_mcp import BlenderMCPServer  # noqa: E402

TASK_ROOT = ROOT / "bench" / "tasks"


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output", default=str(ROOT / "bench" / "results" / "latest"))
    parser.add_argument("--only", default="")
    return parser.parse_args(raw)


def discover_tasks(only: str) -> list[dict]:
    selected = {item.strip() for item in only.split(",") if item.strip()}
    tasks = []
    for task_dir in sorted(TASK_ROOT.iterdir()):
        task_file = task_dir / "task.json"
        expected_file = task_dir / "expected.json"
        if not task_file.is_file() or not expected_file.is_file():
            continue
        if selected and task_dir.name not in selected:
            continue
        task = json.loads(task_file.read_text(encoding="utf-8"))
        task["slug"] = task_dir.name
        task["expected"] = json.loads(expected_file.read_text(encoding="utf-8"))
        tasks.append(task)
    return tasks


def compare(expected, observed, path: str = "") -> list[str]:
    failures: list[str] = []
    if isinstance(expected, dict):
        if "target" in expected and "tolerance" in expected:
            if not isinstance(observed, (int, float)):
                return [f"{path}: expected a number, got {observed!r}"]
            if abs(float(observed) - float(expected["target"])) > float(expected["tolerance"]):
                failures.append(
                    f"{path}: expected {expected['target']} +/- {expected['tolerance']}, "
                    f"got {observed}"
                )
            return failures
        if "min" in expected:
            if not isinstance(observed, (int, float)) or observed < expected["min"]:
                failures.append(f"{path}: expected >= {expected['min']}, got {observed!r}")
            return failures
        for key, value in expected.items():
            child = f"{path}.{key}" if path else key
            if key not in observed:
                failures.append(f"{child}: missing")
                continue
            failures.extend(compare(value, observed[key], child))
        return failures
    if isinstance(expected, list):
        if not isinstance(observed, list) or len(expected) != len(observed):
            failures.append(f"{path}: expected {expected!r}, got {observed!r}")
            return failures
        for index, (child_expected, child_observed) in enumerate(
            zip(expected, observed, strict=False)
        ):
            failures.extend(
                compare(child_expected, child_observed, f"{path}[{index}]")
            )
        return failures
    if isinstance(expected, float) and isinstance(observed, float):
        if abs(expected - observed) > 1e-6:
            failures.append(f"{path}: expected {expected}, got {observed}")
        return failures
    if expected != observed:
        failures.append(f"{path}: expected {expected!r}, got {observed!r}")
    return failures


def main() -> int:
    args = parse_args()
    runs = max(1, int(args.runs))
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    tasks = discover_tasks(args.only)
    if not tasks:
        print("No benchmark tasks found.")
        return 1

    server = BlenderMCPServer(port=0)
    trace_path = output / "trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    summary = {
        "benchmark": "BlenderMCP-Bench",
        "blender": bpy.app.version_string,
        "runs": runs,
        "tasks": {},
        "external_comparison": {
            "performed": False,
            "reason": "Requires a second server with the same LLM, prompt, budget and machine.",
        },
    }

    all_passed = True
    for run_index in range(1, runs + 1):
        for task in tasks:
            slug = task["slug"]
            artifact_dir = output / f"run_{run_index}" / slug
            artifact_dir.mkdir(parents=True, exist_ok=True)
            os.environ["BLENDER_MCP_OUTPUT_DIR"] = str(artifact_dir)
            server.clear_scene(confirm=True)
            started = time.perf_counter()
            error = None
            observed = {}
            try:
                action = getattr(actions, task["runner"])
                observed = action(server, str(artifact_dir))
            except Exception:
                error = traceback.format_exc()
            duration_ms = round((time.perf_counter() - started) * 1000.0, 3)

            failures = [] if error else compare(task["expected"], observed)
            passed = error is None and not failures
            all_passed = all_passed and passed

            try:
                bpy.ops.wm.save_as_mainfile(
                    filepath=str(artifact_dir / "scene.blend"),
                    copy=True,
                )
            except Exception:
                error = error or traceback.format_exc()

            metrics = {
                "task": slug,
                "category": task["category"],
                "run": run_index,
                "passed": passed,
                "duration_ms": duration_ms,
                "expected": task["expected"],
                "observed": observed,
                "failures": failures,
                "error": error,
                "artifacts": {
                    "scene": "scene.blend",
                },
            }
            (artifact_dir / "metrics.json").write_text(
                json.dumps(metrics, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            with trace_path.open("a", encoding="utf-8") as trace:
                trace.write(json.dumps({
                    "event": "task",
                    "task": slug,
                    "run": run_index,
                    "passed": passed,
                    "duration_ms": duration_ms,
                    "failures": failures,
                    "error": error,
                }, sort_keys=True) + "\n")

            entry = summary["tasks"].setdefault(slug, {
                "category": task["category"],
                "runs": [],
            })
            entry["runs"].append({
                "run": run_index,
                "passed": passed,
                "duration_ms": duration_ms,
                "failures": failures,
            })
            print(
                f"[{'PASS' if passed else 'FAIL'}] {slug} run {run_index} "
                f"({duration_ms:.1f} ms)"
            )
            if failures:
                for failure in failures:
                    print(f"  - {failure}")
            if error:
                print(error)

    os.environ.pop("BLENDER_MCP_OUTPUT_DIR", None)
    for entry in summary["tasks"].values():
        durations = [item["duration_ms"] for item in entry["runs"]]
        passes = [item["passed"] for item in entry["runs"]]
        entry["pass_rate"] = round(sum(1 for value in passes if value) / len(passes), 3)
        entry["median_ms"] = round(statistics.median(durations), 3)
    summary["passed_tasks"] = sum(
        1 for entry in summary["tasks"].values() if entry["pass_rate"] == 1.0
    )
    summary["total_tasks"] = len(summary["tasks"])
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        f"SUMMARY {summary['passed_tasks']}/{summary['total_tasks']} "
        f"tasks passed; results in {output}"
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
