"""Validation helpers shared by the Blender benchmark and host tests."""

import math


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def compare(expected, observed, path: str = "") -> list[str]:
    failures: list[str] = []
    if isinstance(expected, dict):
        if "target" in expected and "tolerance" in expected:
            if not _finite_number(observed):
                return [f"{path}: expected a number, got {observed!r}"]
            if abs(float(observed) - float(expected["target"])) > float(expected["tolerance"]):
                failures.append(
                    f"{path}: expected {expected['target']} +/- {expected['tolerance']}, "
                    f"got {observed}"
                )
            return failures
        if "min" in expected:
            if not _finite_number(observed) or observed < expected["min"]:
                failures.append(f"{path}: expected >= {expected['min']}, got {observed!r}")
            return failures
        if not isinstance(observed, dict):
            return [f"{path}: expected an object, got {observed!r}"]
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
        if not _finite_number(observed) or abs(expected - observed) > 1e-6:
            failures.append(f"{path}: expected {expected}, got {observed}")
        return failures
    if (isinstance(expected, bool) and type(observed) is not bool) or expected != observed:
        failures.append(f"{path}: expected {expected!r}, got {observed!r}")
    return failures

