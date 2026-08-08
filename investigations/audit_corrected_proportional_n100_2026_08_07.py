"""Independent, read-only audit of the corrected proportional n=100 campaign.

This auditor deliberately does not import the campaign driver and does not use
any verifier or analysis routine from it.  It reconstructs the canonical slice
from the original n=100 plan, reads every checkpoint and sealed comparator, and
recomputes the statistical decision from first principles.

The only required argument is ``--output``.  The script never writes to that
directory (or to any other campaign/frozen directory); its report is emitted on
stdout.  ``--self-test`` exercises only immutable inputs and deterministic
helpers and never starts a simulation.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import statistics
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"
for _path in (ROOT, EXPERIMENTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import run_rate_allocator_n100 as canonical  # noqa: E402


SCRIPT_PATH = Path(__file__).resolve()
CAMPAIGN_DRIVER_PATH = EXPERIMENTS / "run_corrected_proportional_n100.py"
SPEC_PATH = ROOT / "investigations" / "CORRECTED_PROPORTIONAL_N100_SPEC_2026_08_07.md"
SIM_PATH = ROOT / "sim.py"
CANONICAL_PATH = EXPERIMENTS / "run_rate_allocator_n100.py"
CORE_PATH = EXPERIMENTS / "run_rate_allocator_pilot.py"
HISTORICAL_ROOT = (
    ROOT / "investigations" / "rate_allocator_n100" / "n100_2026-08-06_03"
)
AUDIT_V2_ROOT = (
    ROOT
    / "investigations"
    / "proportional_mechanism_audit_v2"
    / "audit_v2_2026-08-07_01"
)
AUDIT_V2_EQUIVALENCE = AUDIT_V2_ROOT / "production_equivalence.json"
AUDIT_V1_ROOT = (
    ROOT
    / "investigations"
    / "proportional_mechanism_audit"
    / "audit_2026-08-07_01"
)
RESULTS_ROOT = ROOT / "results"
CAMPAIGN_ROOT = (ROOT / "investigations" / "corrected_proportional_n100").resolve()
FROZEN_MANIFEST = (
    ROOT
    / "investigations"
    / "rate_model_revalidation_2026_08_06"
    / "frozen_csv_sha256.txt"
)

ALLOCATORS = ("link_local_equal_share", "network_maxmin")
SAMPLE_IDS = tuple(range(100))
CONSERVATION_TOLERANCE_B = 1e-6
BOOTSTRAP_REPLICATES = 20_000
BOOTSTRAP_SEED = 20260807
EXPECTED_PAIR_ID_SHA256 = (
    "72c14abfa494a0896b79aa75abf5d8071e6697f14e2e323963a869a62bda31da"
)
EXPECTED_BOOTSTRAP_INDEX_SHA256 = (
    "97a42157ab7dd18246ac02f284afb9da83a406f01b467cae35efaab2ad7a654f"
)
EXPECTED_CANONICAL_PLAN_SHA256 = (
    "47099eedb41d1574cc49a6e08a2f7bb20b6c14077531b32b80222be9519291ac"
)
EXPECTED_SOURCE_HASHES = {
    SPEC_PATH: "0bfb2286b52f0dc5266c8e80a08e7d2de8e7508565e5f07b25caee8e4a508090",
    SIM_PATH: "96505cefe2e5aa761b80080d77145bfd384c688ce4a8ca5792f8f7ce17ef59bd",
    CANONICAL_PATH: "7d01a2e598c799b0c533fb650f33b8537f51fa3187f427fcf9ada108d56fd8b4",
    CORE_PATH: "777018e1a408eb5274d5ee87700fc66e4396fd5d39722f625f22e48840efc431",
    AUDIT_V2_ROOT / "COMPLETE.json": (
        "046f980e20312b2ff988ec3fd1a1185cd2df9c261acf4da61168a658661cccd9"
    ),
    AUDIT_V1_ROOT / "COMPLETE.json": (
        "a6e4c00a80c6bfb179af68f9308e2e91e2fab8aaed6ceda10a09cbe9494419ad"
    ),
    HISTORICAL_ROOT / "COMPLETE.json": (
        "c4caaf8bb203eff3b815236c3bc848d8d483b521571c3ab71a47a32f135eadfa"
    ),
}
EXPECTED_CAMPAIGN_DRIVER_SHA256 = (
    "7b65d37635a3d8315517f0076602cb4c663c1c0659ef1dbb3ee56e3053b10f9b"
)
EXPECTED_FROZEN_ROOT_SHA256 = (
    "09a1418e965b9c2d597721ff0d3b1e8db937a19ce667accfa2cf1f469664c24e"
)
NAMED_ANCHORS = {
    ("a072_proportional_3tier_os4_p64_k16__s033", "link_local_equal_share"): (
        0.00630,
        126,
    ),
    ("a079_proportional_2tier_p64_k8__s066", "network_maxmin"): (
        0.00615,
        123,
    ),
}
EXPECTED_PRIOR_ROOT_FILES = frozenset(
    {
        ".run.lock",
        "run_manifest.json",
        "preflight_complete.json",
        "results_long.csv",
        "pairs.csv",
        "historical_deltas.csv",
        "equal_comparison.csv",
        "leave_one_seed_out.csv",
        "arm_analysis.csv",
        "strata_analysis.csv",
        "analysis.json",
        "REPORT.md",
        "runtime.json",
        "gate.json",
        "v2_overlap.json",
    }
)


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _driver_root_inventory_contract() -> Dict[str, Any]:
    """Read, but never import, the driver's final root-inventory contract."""
    try:
        tree = ast.parse(CAMPAIGN_DRIVER_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("cannot parse authorized campaign driver") from exc

    assignments: Dict[str, ast.AST] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name):
                assignments[target.id] = statement.value

    prior_node = assignments.get("PRIOR_FINAL_ROOT_FILES")
    _require(
        isinstance(prior_node, ast.Call)
        and isinstance(prior_node.func, ast.Name)
        and prior_node.func.id == "frozenset"
        and len(prior_node.args) == 1
        and not prior_node.keywords,
        "driver prior-final root allowlist is not a literal frozenset",
    )
    try:
        prior = frozenset(ast.literal_eval(prior_node.args[0]))
    except Exception as exc:
        raise RuntimeError("driver prior-final root allowlist is not literal") from exc
    _require(
        prior and all(isinstance(name, str) and "/" not in name for name in prior),
        "driver prior-final root allowlist contains an invalid name",
    )

    final_node = assignments.get("FINAL_ROOT_FILES")
    _require(
        isinstance(final_node, ast.BinOp)
        and isinstance(final_node.op, ast.BitOr)
        and isinstance(final_node.left, ast.Name)
        and final_node.left.id == "PRIOR_FINAL_ROOT_FILES",
        "driver final root allowlist is not based on the prior-final set",
    )
    try:
        final_additions = frozenset(ast.literal_eval(final_node.right))
    except Exception as exc:
        raise RuntimeError("driver final root additions are not literal") from exc
    final = prior | final_additions

    gate_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_verify_root_artifact_set"
    ]
    _require(len(gate_functions) == 1, "driver root-inventory gate is not unique")
    gate = gate_functions[0]

    def literal_string_set(node: ast.AST) -> frozenset[str] | None:
        try:
            value = ast.literal_eval(node)
        except Exception:
            return None
        if isinstance(value, (set, frozenset)) and all(
            isinstance(item, str) for item in value
        ):
            return frozenset(value)
        return None

    def named_union(
        node: ast.AST,
        *,
        name: str,
        additions: frozenset[str],
        wrap_name_in_set: bool = False,
    ) -> bool:
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.BitOr):
            return False
        left = node.left
        if wrap_name_in_set:
            left_matches = (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "set"
                and len(left.args) == 1
                and isinstance(left.args[0], ast.Name)
                and left.args[0].id == name
                and not left.keywords
            )
        else:
            left_matches = isinstance(left, ast.Name) and left.id == name
        return bool(left_matches and literal_string_set(node.right) == additions)

    def mode_equals(node: ast.AST, value: str) -> bool:
        return (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "mode"
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
            and node.comparators[0].value == value
        )

    local_assignments: Dict[str, ast.AST] = {}
    for node in ast.walk(gate):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                local_assignments[target.id] = node.value

    completion_only = frozenset({"completion_manifest.json"})
    _require(
        named_union(
            local_assignments.get("partial_allowed", ast.Constant(None)),
            name="PRIOR_FINAL_ROOT_FILES",
            additions=completion_only,
        ),
        "driver partial mode is not limited to prior-final plus completion manifest",
    )
    expected_node = local_assignments.get("expected")
    _require(
        isinstance(expected_node, ast.IfExp)
        and mode_equals(expected_node.test, "prior_final")
        and isinstance(expected_node.body, ast.Name)
        and expected_node.body.id == "PRIOR_FINAL_ROOT_FILES"
        and isinstance(expected_node.orelse, ast.Name)
        and expected_node.orelse.id == "FINAL_ROOT_FILES",
        "driver prior-final/final expected-set selection changed",
    )
    accepted_node = local_assignments.get("accepted_sets")
    _require(
        isinstance(accepted_node, ast.List)
        and len(accepted_node.elts) == 1
        and isinstance(accepted_node.elts[0], ast.Call)
        and isinstance(accepted_node.elts[0].func, ast.Name)
        and accepted_node.elts[0].func.id == "set"
        and len(accepted_node.elts[0].args) == 1
        and isinstance(accepted_node.elts[0].args[0], ast.Name)
        and accepted_node.elts[0].args[0].id == "expected",
        "driver accepted-set baseline is not exact",
    )

    partial_branches = [
        statement
        for statement in gate.body
        if isinstance(statement, ast.If) and mode_equals(statement.test, "partial")
    ]
    prior_branches = [
        statement
        for statement in gate.body
        if isinstance(statement, ast.If)
        and mode_equals(statement.test, "prior_final")
    ]
    _require(
        len(partial_branches) == 1 and len(prior_branches) == 1,
        "driver partial/prior-final inventory branches changed",
    )
    partial_branch = partial_branches[0]
    _require(
        not any(
            isinstance(node, ast.Constant) and node.value == "COMPLETE.json"
            for node in ast.walk(partial_branch)
        ),
        "driver partial mode admits COMPLETE.json",
    )
    _require(
        any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "actual"
            and node.func.attr == "issubset"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "partial_allowed"
            for node in ast.walk(partial_branch)
        ),
        "driver partial mode does not enforce its exact allowlist",
    )
    _require(
        any(isinstance(node, ast.Raise) for node in ast.walk(partial_branch)),
        "driver partial allowlist failure does not stop execution",
    )
    prior_branch = prior_branches[0]
    _require(
        any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "accepted_sets"
            and node.func.attr == "append"
            and len(node.args) == 1
            and named_union(
                node.args[0],
                name="expected",
                additions=completion_only,
                wrap_name_in_set=True,
            )
            for node in ast.walk(prior_branch)
        ),
        "driver prior-final mode lacks the exact crash-window alternative",
    )
    _require(
        any(
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "actual"
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.NotIn)
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Name)
            and node.comparators[0].id == "accepted_sets"
            for node in ast.walk(gate)
        ),
        "driver final/prior-final modes do not require exact-set membership",
    )

    execution_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_or_resume"
    ]
    finalizers = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_finalize"
    ]
    _require(
        len(execution_functions) == 1 and len(finalizers) == 1,
        "driver execute/finalize functions are not unique",
    )
    execute = execution_functions[0]
    early_complete_returns = []
    for node in ast.walk(execute):
        if not isinstance(node, ast.If):
            continue
        literals = {
            child.value
            for child in ast.walk(node.test)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
        if "COMPLETE.json" in literals:
            early_complete_returns.append(node)
    _require(
        len(early_complete_returns) == 1
        and any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_verify_complete"
            for node in ast.walk(early_complete_returns[0])
        ),
        "driver resume does not reserve early completion for COMPLETE.json",
    )
    _require(
        not any(
            isinstance(node, ast.Constant) and node.value == "completion_manifest.json"
            for node in ast.walk(execute)
        ),
        "driver resume incorrectly treats completion_manifest.json as complete",
    )
    finalize_literals = [
        node.value
        for node in ast.walk(finalizers[0])
        if isinstance(node, ast.Constant)
        and node.value in {"completion_manifest.json", "COMPLETE.json"}
    ]
    _require(
        finalize_literals.index("completion_manifest.json")
        < finalize_literals.index("COMPLETE.json"),
        "driver final seal write order changed",
    )

    def unique_function(name: str) -> ast.FunctionDef:
        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        _require(len(matches) == 1, f"driver function {name} is not unique")
        return matches[0]

    def has_named_call(
        function: ast.FunctionDef,
        name: str,
        positional_names: Sequence[str] = (),
    ) -> bool:
        for node in ast.walk(function):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
                and len(node.args) >= len(positional_names)
            ):
                continue
            if all(
                isinstance(node.args[index], ast.Name)
                and node.args[index].id == expected
                for index, expected in enumerate(positional_names)
            ):
                return True
        return False

    lock_hasher = unique_function("_locked_run_lock_artifact")
    artifact_metadata = unique_function("_artifact_metadata")
    artifact_inventory = unique_function("_artifact_inventory")
    complete_verifier = unique_function("_verify_complete")
    _require(
        all(
            any(argument.arg == "run_lock" for argument in function.args.args)
            for function in (
                lock_hasher,
                artifact_metadata,
                artifact_inventory,
                finalizers[0],
                complete_verifier,
            )
        ),
        "driver does not thread the held run-lock object through sealing",
    )
    lock_attributes = {
        (node.value.id, node.attr)
        for node in ast.walk(lock_hasher)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }
    _require(
        {("run_lock", "handle"), ("run_lock", "path")} <= lock_attributes,
        "driver lock hasher does not bind both held handle and declared path",
    )
    required_handle_calls = {"flush", "fileno", "tell", "seek", "read"}
    observed_handle_calls = {
        node.func.attr
        for node in ast.walk(lock_hasher)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "handle"
    }
    _require(
        required_handle_calls <= observed_handle_calls,
        "driver lock hasher does not read and restore the held handle",
    )
    _require(
        any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and node.func.attr == "fstat"
            for node in ast.walk(lock_hasher)
        )
        and any(
            isinstance(node, ast.Try)
            and any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "handle"
                and child.func.attr == "seek"
                for statement in node.finalbody
                for child in ast.walk(statement)
            )
            for node in ast.walk(lock_hasher)
        ),
        "driver lock hasher lacks handle-identity or offset-restoration checks",
    )
    _require(
        not any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "_sha256_file")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"open", "read_bytes"}
                )
            )
            for node in ast.walk(lock_hasher)
        ),
        "driver lock hasher reopens the held lock artifact",
    )
    _require(
        has_named_call(
            artifact_metadata,
            "_locked_run_lock_artifact",
            ("path", "run_lock"),
        )
        and has_named_call(
            artifact_inventory,
            "_artifact_metadata",
            ("path", "run_lock"),
        )
        and has_named_call(
            complete_verifier,
            "_artifact_metadata",
            ("path", "run_lock"),
        ),
        "driver artifact inventory/verification bypasses same-handle metadata",
    )
    _require(
        has_named_call(
            finalizers[0],
            "_artifact_inventory",
            ("output", "run_lock"),
        )
        and has_named_call(
            finalizers[0],
            "_verify_complete",
            ("output", "manifest", "run_lock"),
        )
        and has_named_call(
            execute,
            "_verify_complete",
            ("output", "manifest", "run_lock"),
        ),
        "driver does not preserve the held lock through inventory and verification",
    )
    _require(
        any(
            isinstance(node, ast.With)
            and any(
                isinstance(item.optional_vars, ast.Name)
                and item.optional_vars.id == "run_lock"
                and isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "ExclusiveRunLock"
                for item in node.items
            )
            for node in ast.walk(execute)
        ),
        "driver does not retain the ExclusiveRunLock context object",
    )

    enforced_modes = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_verify_root_artifact_set"
        ):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "mode"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                enforced_modes.add(keyword.value.value)

    return {
        "prior": prior,
        "final": final,
        "enforced_modes": enforced_modes,
        "crash_window_resume": True,
        "same_handle_lock_signing": True,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot read JSON {path}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _f64_hex(value: Any) -> str:
    return struct.pack(">d", float(value)).hex()


def _valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except Exception as exc:
        raise RuntimeError(f"{label} is not numeric: {value!r}") from exc
    _require(math.isfinite(number), f"{label} is not finite: {number!r}")
    if positive:
        _require(number > 0.0, f"{label} is not positive: {number!r}")
    else:
        _require(number >= 0.0, f"{label} is negative: {number!r}")
    return number


def _snapshot_tree(root: Path) -> Dict[str, Any]:
    rows: List[List[Any]] = []
    total_bytes = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(ROOT).as_posix()
        size = path.stat().st_size
        total_bytes += size
        rows.append([relative, size, _sha256_file(path)])
    return {
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "root_sha256": _json_digest(rows),
    }


def _protected_tree_snapshot(root: Path) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        _require(not path.is_symlink(), f"protected tree contains a symlink: {path}")
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return {
        "root": root.relative_to(ROOT).as_posix(),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "root_sha256": _json_digest(files),
    }


def _frozen_snapshot() -> Dict[str, Any]:
    lines = [
        line
        for line in FROZEN_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    _require(len(lines) == 63, f"frozen manifest count is {len(lines)}, expected 63")
    total = 0
    for line in lines:
        expected_hash, raw_size, relative = line.split(maxsplit=2)
        path = ROOT / relative
        _require(path.is_file(), f"missing frozen artifact {relative}")
        expected_size = int(raw_size)
        actual_size = path.stat().st_size
        actual_hash = _sha256_file(path)
        _require(
            (actual_size, actual_hash) == (expected_size, expected_hash),
            f"frozen artifact drift: {relative}",
        )
        total += actual_size
    root_hash = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    _require(root_hash == EXPECTED_FROZEN_ROOT_SHA256, "frozen root seal drift")
    return {
        "count": len(lines),
        "total_bytes": total,
        "root_sha256": root_hash,
        "manifest_sha256": _sha256_file(FROZEN_MANIFEST),
        "mismatches": 0,
    }


def _canonical_slice() -> Dict[str, Any]:
    full = canonical.build_plan()
    _require(
        full.get("plan_sha256") == EXPECTED_CANONICAL_PLAN_SHA256,
        "canonical n=100 plan seal drift",
    )
    pairs = [
        pair
        for pair in full["pairs"]
        if pair["config"].get("family") == "static_split"
        and pair["config"].get("runner") == "proportional"
        and pair["config"].get("policy") == "proportional"
        and pair["config"].get("oracle_kind") == "proportional"
        and int(pair["config"].get("ring_size", -1)) in (16, 64)
        and int(pair["config"].get("k", -1)) in (2, 4, 8, 16)
        and pair["config"].get("fabric")
        in ("2tier", "3tier_nb", "3tier_os2", "3tier_os4")
        and int(pair["sample_id"]) in SAMPLE_IDS
    ]
    arm_indexes = sorted({int(pair["arm_index"]) for pair in pairs})
    arms = [full["arms"][index] for index in arm_indexes]
    pair_ids = [pair["pair_id"] for pair in pairs]
    _require(len(arms) == 32, f"canonical proportional arm count is {len(arms)}")
    _require(len(pairs) == 3_200, f"canonical proportional pair count is {len(pairs)}")
    _require(len(set(pair_ids)) == 3_200, "canonical proportional IDs are not unique")
    _require(
        _json_digest(pair_ids) == EXPECTED_PAIR_ID_SHA256,
        "canonical proportional pair-ID digest drift",
    )
    _require(arm_indexes == list(range(48, 80)), "canonical arm indexes are not 48..79")
    _require(
        sorted({int(pair["pair_id"][1:4]) for pair in pairs}) == list(range(49, 81)),
        "canonical retained arm labels are not a049..a080",
    )
    _require(
        Counter(int(pair["sample_id"]) for pair in pairs)
        == Counter({seed: 32 for seed in SAMPLE_IDS}),
        "canonical per-seed pair cardinality drift",
    )
    _require(
        Counter(pair["config"]["arm_id"] for pair in pairs)
        == Counter({arm["arm_id"]: 100 for arm in arms}),
        "canonical per-arm pair cardinality drift",
    )
    _require(
        Counter(pair["execution_order"][0] for pair in pairs)
        == Counter({ALLOCATORS[0]: 1_600, ALLOCATORS[1]: 1_600}),
        "canonical allocator-first balance drift",
    )
    return {"full": full, "arms": arms, "pairs": pairs, "pair_ids": pair_ids}


def _verify_run_plan(manifest: Mapping[str, Any], canonical_slice: Mapping[str, Any]) -> None:
    plan = manifest.get("plan")
    _require(isinstance(plan, dict), "run manifest lacks an embedded plan")
    stored_hash = plan.get("plan_sha256")
    _require(_valid_digest(stored_hash), "embedded plan hash is malformed")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    _require(_json_digest(unsigned) == stored_hash, "embedded plan self-hash mismatch")
    _require(manifest.get("plan_sha256") == stored_hash, "manifest/plan hash mismatch")
    _require(plan.get("pairs") == canonical_slice["pairs"], "run pairs differ from canonical filter")
    _require(plan.get("arms") == canonical_slice["arms"], "run arms differ from canonical filter")
    _require(plan.get("pair_count") == 3_200, "run plan pair count is not 3,200")
    _require(plan.get("simulation_count") == 6_400, "run plan simulation count is not 6,400")
    _require(plan.get("no_n1000_execution_path") is True, "n=1000 path is not sealed off")


def _verify_source_seals() -> Dict[str, Any]:
    observed: Dict[str, str] = {}
    for path, expected in EXPECTED_SOURCE_HASHES.items():
        _require(path.is_file(), f"missing immutable source/reference {path}")
        actual = _sha256_file(path)
        _require(actual == expected, f"immutable source/reference drift: {path}")
        observed[path.relative_to(ROOT).as_posix()] = actual
    driver_hash = _sha256_file(CAMPAIGN_DRIVER_PATH)
    _require(
        driver_hash == EXPECTED_CAMPAIGN_DRIVER_SHA256,
        "authorized corrected n=100 campaign driver drift",
    )
    observed[CAMPAIGN_DRIVER_PATH.relative_to(ROOT).as_posix()] = driver_hash
    return observed


def _verify_signed_reference_bundle(root: Path, *, kind: str) -> Dict[str, Any]:
    complete_path = root / "COMPLETE.json"
    complete = _read_json(complete_path)
    if kind == "audit_v2":
        artifacts = complete.get("artifacts")
        _require(isinstance(artifacts, dict) and artifacts, "Audit v2 artifact seal missing")
        signed = dict(artifacts)
        expected_files = set(signed) | {"COMPLETE.json"}
    elif kind == "historical":
        completion_path = root / "completion_manifest.json"
        _require(
            _sha256_file(completion_path) == complete.get("completion_manifest_sha256"),
            "historical completion-manifest hash mismatch",
        )
        completion = _read_json(completion_path)
        _require(
            _sha256_file(root / "run_manifest.json") == complete.get("run_manifest_sha256"),
            "historical run-manifest hash mismatch",
        )
        signed = {}
        for group in ("checkpoints", "timing_segments", "exports"):
            values = completion.get(group)
            _require(isinstance(values, dict), f"historical {group} seal missing")
            signed.update(values)
        signed["run_manifest.json"] = completion["run_manifest"]
        expected_files = set(signed) | {
            ".run.lock",
            "completion_manifest.json",
            "COMPLETE.json",
        }
    else:
        raise RuntimeError(f"unknown reference bundle kind {kind}")
    for relative, signature in signed.items():
        path = root / relative
        _require(path.is_file(), f"missing signed {kind} artifact {relative}")
        _require(
            path.stat().st_size == int(signature["bytes"])
            and _sha256_file(path) == signature["sha256"],
            f"signed {kind} artifact drift: {relative}",
        )
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    _require(actual_files == expected_files, f"{kind} bundle inventory is not exact")
    return {
        "file_count": len(actual_files),
        "tree": _snapshot_tree(root),
        "complete_sha256": _sha256_file(complete_path),
    }


def _verify_reference_statuses() -> None:
    v2 = _read_json(AUDIT_V2_ROOT / "COMPLETE.json")
    v1 = _read_json(AUDIT_V1_ROOT / "COMPLETE.json")
    historical = _read_json(HISTORICAL_ROOT / "COMPLETE.json")
    _require(
        v2.get("status") == "PASS_READY_FOR_PROPORTIONAL_N100_REVALIDATION",
        "Audit v2 status is not the authorized PASS",
    )
    _require(
        str(v1.get("status", "")).startswith("STOP_BEFORE_N1000"),
        "Audit v1 stop status drift",
    )
    _require(
        historical.get("schema") == "rate-allocator-n100-complete-v1"
        and historical.get("status") == "n100_revalidation_complete_ready_for_analysis"
        and historical.get("plan_sha256") == EXPECTED_CANONICAL_PLAN_SHA256,
        "historical n=100 completion status/plan drift",
    )


def _checkpoint_row_map(checkpoint: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    rows = checkpoint.get("rows")
    _require(isinstance(rows, list) and len(rows) == 2, "checkpoint does not have two rows")
    mapped = {row.get("allocator"): row for row in rows if isinstance(row, dict)}
    _require(set(mapped) == set(ALLOCATORS), "checkpoint allocator inventory is not exact")
    return mapped


def _validate_conservation(
    conservation: Mapping[str, Any], pair: Mapping[str, Any], *, label: str
) -> Dict[str, Any]:
    config = pair["config"]
    p = int(config["ring_size"])
    k = int(config["k"])
    _require(conservation.get("passed") is True, f"{label}: conservation did not pass")
    _require(int(conservation.get("checks", -1)) == p, f"{label}: expected {p} edge checks")
    _require(
        int(conservation.get("foreground_flow_count", -1)) == p * k,
        f"{label}: expected {p * k} foreground flows",
    )
    maximum_error = _finite(
        conservation.get("maximum_abs_error_bytes"),
        f"{label}: maximum conservation error",
    )
    _require(
        maximum_error <= CONSERVATION_TOLERANCE_B,
        f"{label}: conservation error {maximum_error} exceeds tolerance",
    )
    _require(
        conservation.get("maximum_abs_error_bytes_hex") == _f64_hex(maximum_error),
        f"{label}: conservation-error hex mismatch",
    )
    maximum_per_flow = _finite(
        conservation.get("maximum_per_flow_error_bytes"),
        f"{label}: maximum per-flow error",
    )
    _require(
        conservation.get("maximum_per_flow_error_bytes_hex")
        == _f64_hex(maximum_per_flow),
        f"{label}: per-flow-error hex mismatch",
    )
    _require(
        isinstance(conservation.get("non_bit_exact_flow_count"), int)
        and int(conservation["non_bit_exact_flow_count"]) >= 0,
        f"{label}: invalid non-bit-exact flow count",
    )
    aggregate_remaining = _finite(
        conservation.get("remaining_foreground_bytes"),
        f"{label}: aggregate foreground remaining bytes",
    )
    _require(aggregate_remaining == 0.0, f"{label}: aggregate remaining bytes are nonzero")

    # These three fields are the prospective campaign's required live-engine
    # evidence.  They cannot be reconstructed from the historical clipped sum.
    _require(
        conservation.get("foreground_remaining_nonzero_count") == 0,
        f"{label}: individual remaining-byte nonzero count is not zero",
    )
    _require(
        conservation.get("individual_remaining_values_checked") == p * k,
        f"{label}: individual remaining-byte check count is not P*k",
    )
    remaining_min = _finite(
        conservation.get("foreground_remaining_min_bytes"),
        f"{label}: minimum individual remaining bytes",
    )
    remaining_max = _finite(
        conservation.get("foreground_remaining_max_bytes"),
        f"{label}: maximum individual remaining bytes",
    )
    _require(
        remaining_min == 0.0 and remaining_max == 0.0,
        f"{label}: individual foreground remaining-byte evidence is not all zero",
    )
    return {
        "checks": p,
        "foreground_flow_count": p * k,
        "maximum_abs_error_bytes": maximum_error,
        "maximum_per_flow_error_bytes": maximum_per_flow,
        "non_bit_exact_flow_count": int(conservation["non_bit_exact_flow_count"]),
        "remaining_foreground_bytes": aggregate_remaining,
        "foreground_remaining_nonzero_count": 0,
        "individual_remaining_values_checked": p * k,
        "foreground_remaining_min_bytes": remaining_min,
        "foreground_remaining_max_bytes": remaining_max,
    }


def _validate_checkpoint(
    checkpoint: Mapping[str, Any], pair: Mapping[str, Any], plan_sha256: str
) -> Dict[str, Mapping[str, Any]]:
    pair_id = pair["pair_id"]
    _require(
        checkpoint.get("schema") == "rate-allocator-pair-checkpoint-v1",
        f"{pair_id}: checkpoint schema mismatch",
    )
    _require(checkpoint.get("pair_id") == pair_id, f"{pair_id}: pair ID mismatch")
    _require(checkpoint.get("pair_spec") == pair, f"{pair_id}: pair specification mismatch")
    _require(checkpoint.get("plan_sha256") == plan_sha256, f"{pair_id}: plan hash mismatch")
    _require(
        checkpoint.get("pair_gate")
        == {
            "passed": True,
            "initial_digests_equal": True,
            "mutable_instances_distinct": True,
        },
        f"{pair_id}: pair gate mismatch",
    )
    timing = checkpoint.get("parent_timing")
    _require(isinstance(timing, dict), f"{pair_id}: parent timing missing")
    _require(
        isinstance(timing.get("segment_index"), int) and timing["segment_index"] >= 1,
        f"{pair_id}: parent timing segment is invalid",
    )
    _finite(
        timing.get("pool_elapsed_at_checkpoint_s"),
        f"{pair_id}: parent elapsed time",
        positive=True,
    )

    rows = _checkpoint_row_map(checkpoint)
    _require(
        {int(row.get("execution_position", -1)) for row in rows.values()} == {0, 1},
        f"{pair_id}: execution-position inventory mismatch",
    )
    expected_digests = (
        "config_sha256",
        "topology_sha256",
        "ring_sha256",
        "route_sha256",
        "process_initial_sha256",
    )
    for field in expected_digests:
        values = [row.get(field) for row in rows.values()]
        _require(all(_valid_digest(value) for value in values), f"{pair_id}: invalid {field}")
        _require(len(set(values)) == 1, f"{pair_id}: paired {field} mismatch")
    for field in ("topology_instance_id", "simulator_instance_id"):
        values = [row.get(field) for row in rows.values()]
        _require(
            all(isinstance(value, int) for value in values) and len(set(values)) == 2,
            f"{pair_id}: mutable {field} instances are not distinct",
        )

    config = pair["config"]
    for allocator, row in rows.items():
        label = f"{pair_id}/{allocator}"
        _require(row.get("pair_id") == pair_id, f"{label}: row pair ID mismatch")
        _require(row.get("allocator") == allocator, f"{label}: allocator mismatch")
        _require(
            int(row.get("execution_position", -1)) == pair["execution_order"].index(allocator),
            f"{label}: execution position mismatch",
        )
        for field in ("arm_id", "family", "runner", "policy"):
            _require(row.get(field) == config[field], f"{label}: {field} mismatch")
        _require(int(row.get("sample_id", -1)) == int(pair["sample_id"]), f"{label}: seed mismatch")
        _require(row.get("config_sha256") == pair["config_sha256"], f"{label}: config digest mismatch")
        _require(row.get("adaptive_gate") is None, f"{label}: unexpected adaptive gate")
        _require(row.get("congestion_instance_id") is None, f"{label}: unexpected congestion instance")
        _require(row.get("background_instance_id") is None, f"{label}: unexpected background instance")

        completion = _finite(row.get("completion_time_s"), f"{label}: completion", positive=True)
        wall = _finite(row.get("wall_time_s"), f"{label}: wall time", positive=True)
        sim_wall = _finite(
            row.get("simulation_wall_time_s"), f"{label}: simulation wall time", positive=True
        )
        cpu = _finite(row.get("cpu_time_s"), f"{label}: CPU time")
        sim_cpu = _finite(row.get("simulation_cpu_time_s"), f"{label}: simulation CPU time")
        for field, number in (
            ("completion_time_hex", completion),
            ("wall_time_hex", wall),
            ("simulation_wall_time_hex", sim_wall),
            ("cpu_time_hex", cpu),
            ("simulation_cpu_time_hex", sim_cpu),
        ):
            _require(row.get(field) == _f64_hex(number), f"{label}: {field} mismatch")
        ticks = row.get("simulated_ticks")
        _require(isinstance(ticks, int) and ticks > 0, f"{label}: invalid simulated ticks")
        _require(
            int(round(completion / float(config["dt_s"]))) == ticks,
            f"{label}: completion/tick inconsistency",
        )
        _validate_conservation(row.get("conservation", {}), pair, label=label)
    return rows


def _load_campaign_checkpoints(
    output: Path, pairs: Sequence[Mapping[str, Any]], plan_sha256: str
) -> Dict[str, Dict[str, Any]]:
    checkpoint_root = output / "checkpoints"
    _require(checkpoint_root.is_dir(), "campaign checkpoint directory is missing")
    expected = {pair["pair_id"]: pair for pair in pairs}
    actual_paths = list(checkpoint_root.glob("*.json"))
    actual_ids = {path.stem for path in actual_paths}
    _require(actual_ids == set(expected), "campaign checkpoint inventory is not exactly 3,200")
    _require(len(actual_paths) == 3_200, "campaign checkpoint file count is not 3,200")
    unexpected = [
        path.relative_to(checkpoint_root).as_posix()
        for path in checkpoint_root.rglob("*")
        if path.is_file() and path.suffix != ".json"
    ]
    _require(not unexpected, f"unexpected checkpoint artifacts: {unexpected[:3]}")
    checkpoints: Dict[str, Dict[str, Any]] = {}
    for pair in pairs:
        pair_id = pair["pair_id"]
        checkpoint = _read_json(checkpoint_root / f"{pair_id}.json")
        _validate_checkpoint(checkpoint, pair, plan_sha256)
        checkpoints[pair_id] = checkpoint
    return checkpoints


def _historical_comparison(
    checkpoints: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    changed_rows = 0
    delta_ticks: List[int] = []
    relative_deltas: List[float] = []
    maximum_abs_delta_s = 0.0
    material_reversals: List[str] = []
    historical_rows = 0
    for pair in pairs:
        pair_id = pair["pair_id"]
        old_path = HISTORICAL_ROOT / "checkpoints" / f"{pair_id}.json"
        _require(old_path.is_file(), f"historical proportional pair missing: {pair_id}")
        old = _read_json(old_path)
        _require(old.get("pair_spec") == pair, f"historical pair spec drift: {pair_id}")
        old_rows = _checkpoint_row_map(old)
        new_rows = _checkpoint_row_map(checkpoints[pair_id])
        old_allocator_delta = (
            int(old_rows[ALLOCATORS[1]]["simulated_ticks"])
            - int(old_rows[ALLOCATORS[0]]["simulated_ticks"])
        )
        new_allocator_delta = (
            int(new_rows[ALLOCATORS[1]]["simulated_ticks"])
            - int(new_rows[ALLOCATORS[0]]["simulated_ticks"])
        )
        if (old_allocator_delta <= -2 and new_allocator_delta >= 2) or (
            old_allocator_delta >= 2 and new_allocator_delta <= -2
        ):
            material_reversals.append(pair_id)
        for allocator in ALLOCATORS:
            label = f"{pair_id}/{allocator}"
            old_row = old_rows[allocator]
            new_row = new_rows[allocator]
            historical_rows += 1
            for field in (
                "config_sha256",
                "topology_sha256",
                "ring_sha256",
                "route_sha256",
                "process_initial_sha256",
            ):
                _require(old_row.get(field) == new_row.get(field), f"historical {field} mismatch: {label}")
            old_time = _finite(old_row.get("completion_time_s"), f"historical completion {label}", positive=True)
            new_time = float(new_row["completion_time_s"])
            _require(old_row.get("completion_time_hex") == _f64_hex(old_time), f"historical completion hex mismatch: {label}")
            tick_delta = int(new_row["simulated_ticks"]) - int(old_row["simulated_ticks"])
            relative = (new_time - old_time) / old_time
            diagnostics = new_row.get("reference_diagnostics")
            _require(
                isinstance(diagnostics, dict)
                and diagnostics.get("schema")
                == "corrected-proportional-reference-diagnostics-v1",
                f"historical reference diagnostics missing: {label}",
            )
            expected_historical = {
                "pair_id": pair_id,
                "allocator": allocator,
                "corrected_completion_time_s": new_time,
                "corrected_completion_time_hex": new_row["completion_time_hex"],
                "corrected_simulated_ticks": int(new_row["simulated_ticks"]),
                "completion_time_s": old_time,
                "completion_time_hex": old_row["completion_time_hex"],
                "simulated_ticks": int(old_row["simulated_ticks"]),
                "corrected_minus_historical_s": new_time - old_time,
                "corrected_minus_historical_ticks": tick_delta,
                "corrected_over_historical": new_time / old_time,
                "relative_delta": new_time / old_time - 1.0,
                "completion_binary64_equal": (
                    new_row["completion_time_hex"] == old_row["completion_time_hex"]
                ),
            }
            _require(
                diagnostics.get("historical_proportional") == expected_historical,
                f"stored historical diagnostics do not recompute: {label}",
            )
            if new_row["completion_time_hex"] != old_row["completion_time_hex"]:
                changed_rows += 1
            delta_ticks.append(tick_delta)
            relative_deltas.append(relative)
            maximum_abs_delta_s = max(maximum_abs_delta_s, abs(new_time - old_time))
    _require(historical_rows == 6_400, "historical proportional row join is not bijective")
    return {
        "pair_count": 3_200,
        "row_count": historical_rows,
        "changed_row_count": changed_rows,
        "unchanged_row_count": historical_rows - changed_rows,
        "delta_tick_min": min(delta_ticks),
        "delta_tick_max": max(delta_ticks),
        "relative_delta_min": min(relative_deltas),
        "relative_delta_max": max(relative_deltas),
        "maximum_absolute_delta_s": maximum_abs_delta_s,
        "material_reversal_count": len(material_reversals),
        "material_reversal_pair_ids": material_reversals,
    }


def _audit_v2_overlap(
    checkpoints: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    bundle = _read_json(AUDIT_V2_EQUIVALENCE)
    _require(
        bundle.get("schema") == "proportional-mechanism-audit-v2-production-equivalence-v1",
        "Audit v2 production-equivalence schema mismatch",
    )
    items = bundle.get("pairs")
    _require(isinstance(items, list) and len(items) == 30, "Audit v2 overlap is not 30 pairs")
    seen: set[str] = set()
    common_conservation_fields = (
        "checks",
        "foreground_flow_count",
        "maximum_abs_error_bytes",
        "maximum_abs_error_bytes_hex",
        "maximum_per_flow_error_bytes",
        "maximum_per_flow_error_bytes_hex",
        "non_bit_exact_flow_count",
        "passed",
        "remaining_foreground_bytes",
    )
    for item in items:
        pair_id = item["pair_id"]
        _require(pair_id not in seen, f"duplicate Audit v2 overlap pair {pair_id}")
        seen.add(pair_id)
        _require(pair_id in checkpoints, f"Audit v2 overlap missing from campaign: {pair_id}")
        expected_pair = item.get("fresh_pair_worker")
        _require(isinstance(expected_pair, dict), f"Audit v2 fresh worker record missing: {pair_id}")
        _require(
            expected_pair.get("pair_spec") == checkpoints[pair_id].get("pair_spec"),
            f"Audit v2 pair-spec mismatch: {pair_id}",
        )
        expected_rows = _checkpoint_row_map(expected_pair)
        actual_rows = _checkpoint_row_map(checkpoints[pair_id])
        for allocator in ALLOCATORS:
            expected = expected_rows[allocator]
            actual = actual_rows[allocator]
            label = f"{pair_id}/{allocator}"
            for field in (
                "completion_time_s",
                "completion_time_hex",
                "simulated_ticks",
                "config_sha256",
                "topology_sha256",
                "ring_sha256",
                "route_sha256",
                "process_initial_sha256",
            ):
                _require(actual.get(field) == expected.get(field), f"Audit v2 {field} mismatch: {label}")
            for field in common_conservation_fields:
                _require(
                    actual.get("conservation", {}).get(field)
                    == expected.get("conservation", {}).get(field),
                    f"Audit v2 conservation {field} mismatch: {label}",
                )
    _require(len(seen) == 30, "Audit v2 overlap pair count drift")
    for (pair_id, allocator), (nominal_s, ticks) in NAMED_ANCHORS.items():
        row = _checkpoint_row_map(checkpoints[pair_id])[allocator]
        _require(int(row["simulated_ticks"]) == ticks, f"named anchor tick mismatch: {pair_id}/{allocator}")
        _require(
            math.isclose(float(row["completion_time_s"]), nominal_s, rel_tol=0.0, abs_tol=1e-14),
            f"named anchor completion mismatch: {pair_id}/{allocator}",
        )
    return {
        "pair_count": len(seen),
        "row_count": 2 * len(seen),
        "named_anchor_count": len(NAMED_ANCHORS),
        "pair_ids_sha256": _json_digest(sorted(seen)),
    }


def _equal_pair_map(full_plan: Mapping[str, Any]) -> Dict[Tuple[str, int, int, int], Mapping[str, Any]]:
    mapped: Dict[Tuple[str, int, int, int], Mapping[str, Any]] = {}
    for pair in full_plan["pairs"]:
        config = pair["config"]
        if not (
            config.get("family") == "static_split"
            and config.get("runner") == "simple"
            and config.get("policy") == "equal"
            and config.get("fabric") in ("2tier", "3tier_nb", "3tier_os2", "3tier_os4")
            and int(config.get("ring_size", -1)) in (16, 64)
            and int(config.get("k", -1)) in (2, 4, 8, 16)
            and int(pair["sample_id"]) in SAMPLE_IDS
        ):
            continue
        key = (
            str(config["fabric"]),
            int(config["ring_size"]),
            int(config["k"]),
            int(pair["sample_id"]),
        )
        _require(key not in mapped, f"duplicate equal comparator key {key}")
        mapped[key] = pair
    _require(len(mapped) == 3_200, f"equal comparator map has {len(mapped)} pairs")
    return mapped


def _equal_comparison(
    checkpoints: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    full_plan: Mapping[str, Any],
) -> Dict[str, Any]:
    equal_map = _equal_pair_map(full_plan)
    amplifications: Dict[str, List[float]] = {allocator: [] for allocator in ALLOCATORS}
    claim_triggers: List[Dict[str, Any]] = []
    equal_allocator_differences = 0
    joined = 0
    used_equal_ids: set[str] = set()
    for pair in pairs:
        config = pair["config"]
        key = (
            str(config["fabric"]),
            int(config["ring_size"]),
            int(config["k"]),
            int(pair["sample_id"]),
        )
        equal_pair = equal_map[key]
        equal_id = equal_pair["pair_id"]
        _require(equal_id not in used_equal_ids, f"equal comparator reused: {equal_id}")
        used_equal_ids.add(equal_id)
        equal_path = HISTORICAL_ROOT / "checkpoints" / f"{equal_id}.json"
        _require(equal_path.is_file(), f"equal comparator checkpoint missing: {equal_id}")
        equal_checkpoint = _read_json(equal_path)
        _require(equal_checkpoint.get("pair_spec") == equal_pair, f"equal pair-spec mismatch: {equal_id}")
        equal_rows = _checkpoint_row_map(equal_checkpoint)
        prop_rows = _checkpoint_row_map(checkpoints[pair["pair_id"]])
        if (
            equal_rows[ALLOCATORS[0]]["completion_time_hex"]
            != equal_rows[ALLOCATORS[1]]["completion_time_hex"]
        ):
            equal_allocator_differences += 1
        for allocator in ALLOCATORS:
            joined += 1
            equal_row = equal_rows[allocator]
            prop_row = prop_rows[allocator]
            label = f"{pair['pair_id']}/{allocator}"
            _require(
                equal_row.get("config_sha256") != prop_row.get("config_sha256"),
                f"equal/proportional config digests unexpectedly match: {label}",
            )
            for field in (
                "topology_sha256",
                "ring_sha256",
                "route_sha256",
                "process_initial_sha256",
            ):
                _require(equal_row.get(field) == prop_row.get(field), f"equal join {field} mismatch: {label}")
            equal_time = _finite(equal_row.get("completion_time_s"), f"equal completion {label}", positive=True)
            prop_time = float(prop_row["completion_time_s"])
            amplifications[allocator].append(equal_time / prop_time)
            tick_delta = int(prop_row["simulated_ticks"]) - int(equal_row["simulated_ticks"])
            diagnostics = prop_row.get("reference_diagnostics", {})
            expected_equal = {
                "pair_id": equal_id,
                "allocator": allocator,
                "completion_time_s": equal_time,
                "completion_time_hex": equal_row["completion_time_hex"],
                "simulated_ticks": int(equal_row["simulated_ticks"]),
                "corrected_completion_time_s": prop_time,
                "corrected_completion_time_hex": prop_row["completion_time_hex"],
                "corrected_simulated_ticks": int(prop_row["simulated_ticks"]),
                "equal_over_corrected_proportional": equal_time / prop_time,
                "corrected_proportional_minus_equal_s": prop_time - equal_time,
                "corrected_proportional_minus_equal_ticks": tick_delta,
                "claim_review_trigger": tick_delta >= 2,
            }
            _require(
                diagnostics.get("matched_equal_policy") == expected_equal,
                f"stored equal diagnostics do not recompute: {label}",
            )
            if tick_delta >= 2:
                claim_triggers.append(
                    {
                        "pair_id": pair["pair_id"],
                        "equal_pair_id": equal_id,
                        "allocator": allocator,
                        "proportional_minus_equal_ticks": tick_delta,
                    }
                )
    _require(len(used_equal_ids) == 3_200 and joined == 6_400, "equal comparator join is not bijective")
    # This is a property of this exact matched static subset, not a general
    # allocator identity.  The audit verifies it rather than relying on it.
    _require(
        equal_allocator_differences == 0,
        "matched static equal subset is not allocator-identical as sealed",
    )
    return {
        "pair_count": len(used_equal_ids),
        "row_count": joined,
        "equal_allocator_different_pair_count": equal_allocator_differences,
        "claim_trigger_count": len(claim_triggers),
        "claim_triggers": claim_triggers,
        "amplification": {
            allocator: {
                "geometric_mean": math.exp(sum(math.log(value) for value in values) / len(values)),
                "median": float(np.median(np.asarray(values, dtype=np.float64))),
                "minimum": min(values),
                "maximum": max(values),
            }
            for allocator, values in amplifications.items()
        },
    }


def _tick_class(delta_ticks: int) -> str:
    if delta_ticks <= -2:
        return "maxmin_faster_by_2plus"
    if delta_ticks == 0:
        return "exact_tie"
    if delta_ticks in (-1, 1):
        return "one_tick_tie"
    if delta_ticks >= 2:
        return "maxmin_slower_by_2plus"
    raise AssertionError("unreachable tick class")


def _bootstrap_index_matrix(seed_count: int) -> Tuple[np.ndarray, Dict[str, Any]]:
    generator = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indexes = generator.integers(
        0,
        seed_count,
        size=(BOOTSTRAP_REPLICATES, seed_count),
        dtype=np.uint32,
    )
    little_endian = np.ascontiguousarray(indexes.astype("<u4", copy=False))
    metadata = {
        "rng": f"PCG64({BOOTSTRAP_SEED})",
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_index_shape": [BOOTSTRAP_REPLICATES, seed_count],
        "bootstrap_index_dtype": "<u4",
        "bootstrap_index_sha256": hashlib.sha256(
            little_endian.tobytes(order="C")
        ).hexdigest(),
    }
    return indexes, metadata


def _paired_bootstrap(log_values: Sequence[float], indexes: np.ndarray) -> Dict[str, Any]:
    values = np.asarray(log_values, dtype=np.float64)
    _require(values.shape == (indexes.shape[1],), "bootstrap value/index shape mismatch")
    replicate_log_means = values[indexes].mean(axis=1)
    ratios = np.exp(replicate_log_means)
    return {
        "point_estimate": math.exp(float(values.mean())),
        "ci95_low": float(np.quantile(ratios, 0.025, method="linear")),
        "ci95_high": float(np.quantile(ratios, 0.975, method="linear")),
    }


def _descriptive(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    _require(bool(records), "cannot summarize an empty record set")
    ratios = np.asarray([float(record["ratio"]) for record in records], dtype=np.float64)
    delta_s = np.asarray([float(record["delta_s"]) for record in records], dtype=np.float64)
    delta_ticks = np.asarray([int(record["delta_ticks"]) for record in records], dtype=np.int64)
    classes = Counter(_tick_class(int(value)) for value in delta_ticks)
    return {
        "pair_count": len(records),
        "geometric_mean_ratio": math.exp(float(np.log(ratios).mean())),
        "median_ratio": float(np.median(ratios)),
        "minimum_ratio": float(ratios.min()),
        "maximum_ratio": float(ratios.max()),
        "mean_signed_delta_ms": float(delta_s.mean() * 1e3),
        "median_signed_delta_ms": float(np.median(delta_s) * 1e3),
        "mean_absolute_delta_ms": float(np.abs(delta_s).mean() * 1e3),
        "maximum_absolute_delta_ms": float(np.abs(delta_s).max() * 1e3),
        "minimum_delta_ms": float(delta_s.min() * 1e3),
        "maximum_delta_ms": float(delta_s.max() * 1e3),
        "mean_signed_delta_ticks": float(delta_ticks.mean()),
        "mean_absolute_delta_ticks": float(np.abs(delta_ticks).mean()),
        "maximum_absolute_delta_ticks": int(np.abs(delta_ticks).max()),
        "minimum_delta_ticks": int(delta_ticks.min()),
        "maximum_delta_ticks": int(delta_ticks.max()),
        "tick_counts": {
            name: int(classes.get(name, 0))
            for name in (
                "maxmin_faster_by_2plus",
                "exact_tie",
                "one_tick_tie",
                "maxmin_slower_by_2plus",
            )
        },
    }


def _scientific_analysis(
    checkpoints: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    historical: Mapping[str, Any],
    equal: Mapping[str, Any],
) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    for pair in pairs:
        rows = _checkpoint_row_map(checkpoints[pair["pair_id"]])
        local = rows[ALLOCATORS[0]]
        maxmin = rows[ALLOCATORS[1]]
        local_time = float(local["completion_time_s"])
        maxmin_time = float(maxmin["completion_time_s"])
        record = {
            "pair_id": pair["pair_id"],
            "arm_id": pair["config"]["arm_id"],
            "fabric": pair["config"]["fabric"],
            "P": int(pair["config"]["ring_size"]),
            "k": int(pair["config"]["k"]),
            "sample_id": int(pair["sample_id"]),
            "ratio": maxmin_time / local_time,
            "delta_s": maxmin_time - local_time,
            "delta_ticks": int(maxmin["simulated_ticks"]) - int(local["simulated_ticks"]),
        }
        _require(record["ratio"] > 0.0 and math.isfinite(record["ratio"]), "invalid allocator ratio")
        records.append(record)
    _require(len(records) == 3_200, "scientific record count is not 3,200 paired observations")

    indexes, bootstrap_metadata = _bootstrap_index_matrix(100)
    _require(
        bootstrap_metadata["bootstrap_index_sha256"]
        == EXPECTED_BOOTSTRAP_INDEX_SHA256,
        "bootstrap resampling-index digest drift",
    )
    records_by_seed: Dict[int, List[Mapping[str, Any]]] = defaultdict(list)
    records_by_arm: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_seed[int(record["sample_id"])].append(record)
        records_by_arm[str(record["arm_id"])].append(record)
    _require(set(records_by_seed) == set(SAMPLE_IDS), "global bootstrap seed inventory mismatch")
    _require(set(map(len, records_by_seed.values())) == {32}, "global seed clusters are not size 32")
    seed_log_means = [
        sum(math.log(float(record["ratio"])) for record in records_by_seed[seed]) / 32.0
        for seed in SAMPLE_IDS
    ]
    global_bootstrap = {
        **_paired_bootstrap(seed_log_means, indexes),
        **bootstrap_metadata,
        "cluster_count": 100,
        "pairs_per_cluster": 32,
    }

    per_arm: Dict[str, Any] = {}
    for arm_id in sorted(records_by_arm):
        arm_records = sorted(records_by_arm[arm_id], key=lambda row: int(row["sample_id"]))
        _require(
            [int(record["sample_id"]) for record in arm_records] == list(SAMPLE_IDS),
            f"per-arm paired seed inventory mismatch: {arm_id}",
        )
        arm_bootstrap = _paired_bootstrap(
            [math.log(float(record["ratio"])) for record in arm_records],
            indexes,
        )
        per_arm[arm_id] = {
            **_descriptive(arm_records),
            "ci95_low": arm_bootstrap["ci95_low"],
            "ci95_high": arm_bootstrap["ci95_high"],
            "bootstrap_index_sha256": bootstrap_metadata["bootstrap_index_sha256"],
            "multiplicity_adjusted": False,
        }

    strata: Dict[str, Dict[str, Any]] = {"fabric": {}, "P": {}, "k": {}}
    for dimension in strata:
        values = sorted({record[dimension] for record in records}, key=str)
        for value in values:
            selected = [record for record in records if record[dimension] == value]
            strata[dimension][str(value)] = _descriptive(selected)

    loo: List[Dict[str, Any]] = []
    total_log = sum(math.log(float(record["ratio"])) for record in records)
    for seed in SAMPLE_IDS:
        removed = sum(math.log(float(record["ratio"])) for record in records_by_seed[seed])
        estimate = math.exp((total_log - removed) / (3_200 - 32))
        loo.append({"sample_id": seed, "geometric_mean_ratio": estimate})
    point = float(global_bootstrap["point_estimate"])
    loo_values = [float(item["geometric_mean_ratio"]) for item in loo]
    if point < 1.0:
        single_seed_dependence = any(value >= 1.0 for value in loo_values)
    elif point > 1.0:
        single_seed_dependence = any(value < 1.0 for value in loo_values)
    else:
        single_seed_dependence = False
    ci_contains_one = (
        float(global_bootstrap["ci95_low"]) <= 1.0
        <= float(global_bootstrap["ci95_high"])
    )
    review_reasons: List[str] = []
    if ci_contains_one:
        review_reasons.append("global_ci_contains_one")
    if int(equal["claim_trigger_count"]) > 0:
        review_reasons.append("same_allocator_equal_policy_claim_trigger")
    if int(historical["material_reversal_count"]) > 0:
        review_reasons.append("material_historical_ordering_reversal")
    if single_seed_dependence:
        review_reasons.append("single_seed_dependence")
    if (
        float(global_bootstrap["ci95_high"]) < 1.0
        and not review_reasons
    ):
        decision = "READY_TO_DECIDE_PROPORTIONAL_N1000_SCOPE"
    else:
        decision = "REVIEW_CORRECTED_N100_EFFECTS_BEFORE_SCALING"
    return {
        "estimand": "T_network_maxmin/T_link_local",
        "global": {**_descriptive(records), **global_bootstrap},
        "per_arm": per_arm,
        "strata": strata,
        "leave_one_seed_out": {
            "values": loo,
            "minimum": min(loo_values),
            "maximum": max(loo_values),
            "single_seed_dependence": single_seed_dependence,
        },
        "decision": decision,
        "review_reasons": review_reasons,
        "historical_changed_row_count": int(historical["changed_row_count"]),
        "historical_max_abs_delta_s": float(historical["maximum_absolute_delta_s"]),
        "historical_material_reversal_count": int(historical["material_reversal_count"]),
        "equal_amplification": equal["amplification"],
    }


def _assert_tree_matches(actual: Any, expected: Any, *, path: str) -> None:
    """Require an exported payload to contain an independently computed tree.

    Dictionaries may contain additional provenance keys, but every independent
    key and every list element must be present and equal.  Floats use a tight
    comparison to tolerate only harmless JSON/CSV decimal formatting.
    """
    if isinstance(expected, dict):
        _require(isinstance(actual, dict), f"{path}: expected an object")
        for key, value in expected.items():
            _require(key in actual, f"{path}: missing key {key}")
            _assert_tree_matches(actual[key], value, path=f"{path}.{key}")
        return
    if isinstance(expected, list):
        _require(isinstance(actual, list), f"{path}: expected a list")
        _require(len(actual) == len(expected), f"{path}: list length mismatch")
        for index, (observed, wanted) in enumerate(zip(actual, expected)):
            _assert_tree_matches(observed, wanted, path=f"{path}[{index}]")
        return
    if isinstance(expected, float):
        _require(
            isinstance(actual, (int, float))
            and math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-15),
            f"{path}: numeric mismatch ({actual!r} != {expected!r})",
        )
        return
    _require(actual == expected, f"{path}: mismatch ({actual!r} != {expected!r})")


def _verify_analysis_export(
    recorded: Mapping[str, Any],
    independent: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
) -> None:
    _require(
        recorded.get("schema") == "corrected-proportional-n100-analysis-v1",
        "analysis.json schema mismatch",
    )
    _require(recorded.get("status") == independent["decision"], "analysis status mismatch")
    _require(recorded.get("paired_row_count") == 3_200, "analysis paired count mismatch")
    _require(
        recorded.get("allocator_rows_not_treated_as_independent") is True,
        "analysis treats allocator rows as independent",
    )
    _require(
        recorded.get("estimand")
        == "R=T_network_maxmin/T_link_local; R<1 means network max-min faster",
        "analysis estimand mismatch",
    )
    observed_global = recorded.get("global", {})
    expected_global = independent["global"]
    global_field_map = {
        "pair_count": "pair_count",
        "geometric_mean_ratio": "geometric_mean_ratio",
        "median_ratio": "median_ratio",
        "minimum_ratio": "minimum_ratio",
        "maximum_ratio": "maximum_ratio",
        "signed_delta_ms_mean": "mean_signed_delta_ms",
        "signed_delta_ms_median": "median_signed_delta_ms",
        "signed_delta_ms_min": "minimum_delta_ms",
        "signed_delta_ms_max": "maximum_delta_ms",
        "absolute_delta_ms_mean": "mean_absolute_delta_ms",
        "absolute_delta_ms_max": "maximum_absolute_delta_ms",
        "signed_delta_ticks_mean": "mean_signed_delta_ticks",
        "signed_delta_ticks_min": "minimum_delta_ticks",
        "signed_delta_ticks_max": "maximum_delta_ticks",
        "absolute_delta_ticks_mean": "mean_absolute_delta_ticks",
        "absolute_delta_ticks_max": "maximum_absolute_delta_ticks",
    }
    for observed_name, expected_name in global_field_map.items():
        _assert_tree_matches(
            observed_global.get(observed_name),
            expected_global[expected_name],
            path=f"analysis.global.{observed_name}",
        )
    _require(
        observed_global.get("tick_class_counts") == expected_global["tick_counts"],
        "analysis global tick counts mismatch",
    )
    observed_bootstrap = observed_global.get("bootstrap", {})
    expected_bootstrap_keys = (
        "point_estimate",
        "ci95_low",
        "ci95_high",
        "bootstrap_replicates",
        "rng",
        "bootstrap_index_shape",
        "bootstrap_index_dtype",
        "bootstrap_index_sha256",
    )
    for key in expected_bootstrap_keys:
        _assert_tree_matches(
            observed_bootstrap.get(key),
            expected_global[key],
            path=f"analysis.global.bootstrap.{key}",
        )
    _require(
        observed_bootstrap.get("quantiles") == [0.025, 0.975]
        and observed_bootstrap.get("quantile_method") == "linear",
        "analysis bootstrap quantile contract mismatch",
    )

    observed_arms = {item["arm_id"]: item for item in recorded.get("by_arm", [])}
    _require(set(observed_arms) == set(independent["per_arm"]), "analysis per-arm inventory mismatch")
    for arm_id, expected in independent["per_arm"].items():
        item = observed_arms[arm_id]
        _require(
            item.get("multiplicity_note")
            == "descriptive_per_arm_interval_no_adjusted_significance_claim",
            f"analysis per-arm multiplicity note mismatch: {arm_id}",
        )
        for observed_name, expected_name in global_field_map.items():
            _assert_tree_matches(
                item.get("descriptive", {}).get(observed_name),
                expected[expected_name],
                path=f"analysis.by_arm.{arm_id}.{observed_name}",
            )
        _require(
            item.get("descriptive", {}).get("tick_class_counts") == expected["tick_counts"],
            f"analysis per-arm tick counts mismatch: {arm_id}",
        )
        for observed_name, expected_name in (
            ("point_estimate", "geometric_mean_ratio"),
            ("ci95_low", "ci95_low"),
            ("ci95_high", "ci95_high"),
            ("bootstrap_index_sha256", "bootstrap_index_sha256"),
        ):
            _assert_tree_matches(
                item.get("bootstrap", {}).get(observed_name),
                expected[expected_name],
                path=f"analysis.by_arm.{arm_id}.bootstrap.{observed_name}",
            )
        _require(
            item.get("bootstrap", {}).get("bootstrap_replicates") == BOOTSTRAP_REPLICATES
            and item.get("bootstrap", {}).get("rng") == f"PCG64({BOOTSTRAP_SEED})"
            and item.get("bootstrap", {}).get("bootstrap_index_shape") == [20_000, 100]
            and item.get("bootstrap", {}).get("bootstrap_index_dtype") == "<u4"
            and item.get("bootstrap", {}).get("quantile_method") == "linear",
            f"analysis per-arm bootstrap contract mismatch: {arm_id}",
        )

    observed_strata = {
        (item["dimension"], str(item["value"])): item["descriptive"]
        for item in recorded.get("strata", [])
    }
    expected_strata_keys = {
        ("fabric", value) for value in independent["strata"]["fabric"]
    } | {("ring_size", value) for value in independent["strata"]["P"]} | {
        ("k", value) for value in independent["strata"]["k"]
    }
    _require(set(observed_strata) == expected_strata_keys, "analysis stratum inventory mismatch")
    for dimension, value in expected_strata_keys:
        source_dimension = "P" if dimension == "ring_size" else dimension
        expected = independent["strata"][source_dimension][value]
        observed = observed_strata[(dimension, value)]
        for observed_name, expected_name in global_field_map.items():
            _assert_tree_matches(
                observed.get(observed_name),
                expected[expected_name],
                path=f"analysis.strata.{dimension}.{value}.{observed_name}",
            )
        _require(
            observed.get("tick_class_counts") == expected["tick_counts"],
            f"analysis stratum tick counts mismatch: {dimension}/{value}",
        )

    loo = recorded.get("leave_one_seed_out", {})
    expected_loo = independent["leave_one_seed_out"]
    _require(
        loo.get("single_seed_dependence") == expected_loo["single_seed_dependence"],
        "analysis leave-one-seed dependence mismatch",
    )
    _assert_tree_matches(
        loo.get("minimum_geometric_mean_ratio"),
        expected_loo["minimum"],
        path="analysis.leave_one_seed_out.minimum",
    )
    _assert_tree_matches(
        loo.get("maximum_geometric_mean_ratio"),
        expected_loo["maximum"],
        path="analysis.leave_one_seed_out.maximum",
    )
    expected_loo_rows = {row["sample_id"]: row["geometric_mean_ratio"] for row in expected_loo["values"]}
    observed_loo_rows = {int(row["omitted_seed"]): row for row in loo.get("rows", [])}
    _require(set(observed_loo_rows) == set(SAMPLE_IDS), "analysis LOO seed inventory mismatch")
    for seed, expected_value in expected_loo_rows.items():
        _assert_tree_matches(
            observed_loo_rows[seed].get("geometric_mean_ratio"),
            expected_value,
            path=f"analysis.leave_one_seed_out.{seed}",
        )

    # Recompute diagnostics not retained in the compact independent summary.
    ordering_class_changes = 0
    trigger_pairs = 0
    for checkpoint in checkpoints.values():
        rows = _checkpoint_row_map(checkpoint)
        new_delta = int(rows[ALLOCATORS[1]]["simulated_ticks"]) - int(rows[ALLOCATORS[0]]["simulated_ticks"])
        old_delta = (
            int(rows[ALLOCATORS[1]]["reference_diagnostics"]["historical_proportional"]["simulated_ticks"])
            - int(rows[ALLOCATORS[0]]["reference_diagnostics"]["historical_proportional"]["simulated_ticks"])
        )
        if _tick_class(old_delta) != _tick_class(new_delta) and abs(old_delta) >= 2 and abs(new_delta) >= 2:
            ordering_class_changes += 1
        if any(
            row["reference_diagnostics"]["matched_equal_policy"]["claim_review_trigger"]
            for row in rows.values()
        ):
            trigger_pairs += 1
    historical_rows = [
        row["reference_diagnostics"]["historical_proportional"]
        for checkpoint in checkpoints.values()
        for row in checkpoint["rows"]
    ]
    expected_historical = {
        "allocator_row_count": 6_400,
        "changed_allocator_rows": independent["historical_changed_row_count"],
        "unchanged_allocator_rows": 6_400 - independent["historical_changed_row_count"],
        "maximum_absolute_completion_delta_s": independent["historical_max_abs_delta_s"],
        "maximum_absolute_tick_delta": max(abs(int(row["corrected_minus_historical_ticks"])) for row in historical_rows),
        "maximum_absolute_relative_delta": max(abs(float(row["relative_delta"])) for row in historical_rows),
        "material_pair_ordering_reversals": independent["historical_material_reversal_count"],
        "ordering_class_changes_outside_one_tick": ordering_class_changes,
        "interpretation": "correction_impact_diagnostic_not_treatment_effect",
    }
    _assert_tree_matches(recorded.get("historical_correction"), expected_historical, path="analysis.historical_correction")
    expected_equal = {
        "matched_pair_count": 3_200,
        "matched_allocator_row_count": 6_400,
        "observed_allocator_identical_pair_count": 3_200,
        "link_local_equal_over_corrected_proportional_geomean": independent["equal_amplification"][ALLOCATORS[0]]["geometric_mean"],
        "network_maxmin_equal_over_corrected_proportional_geomean": independent["equal_amplification"][ALLOCATORS[1]]["geometric_mean"],
        "claim_review_trigger_pair_count": trigger_pairs,
        "allocator_identity_was_verified_not_assumed": True,
        "no_cross_allocator_ratio_identity_assumed": True,
    }
    _assert_tree_matches(recorded.get("equal_policy_comparator"), expected_equal, path="analysis.equal_policy_comparator")
    expected_triggers = {
        "ci_contains_one_inclusive": expected_global["ci95_low"] <= 1.0 <= expected_global["ci95_high"],
        "same_allocator_equal_policy_claim_trigger": trigger_pairs > 0,
        "material_historical_ordering_reversal": independent["historical_material_reversal_count"] > 0,
        "single_seed_dependence": expected_loo["single_seed_dependence"],
    }
    _require(recorded.get("review_triggers") == expected_triggers, "analysis review-trigger mapping mismatch")
    _require(
        recorded.get("scope_limits")
        == [
            "static proportional matrix only",
            "no controller, congestion, background, TCP, or population-wide claim",
            "completion does not authorize n1000",
        ],
        "analysis scope limits mismatch",
    )


def _verify_completion_bundle(output: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    completion_path = output / "completion_manifest.json"
    complete_path = output / "COMPLETE.json"
    _require(completion_path.is_file(), "completion_manifest.json is missing")
    _require(complete_path.is_file(), "COMPLETE.json is missing")
    completion = _read_json(completion_path)
    complete = _read_json(complete_path)
    _require(
        complete.get("completion_manifest_sha256") == _sha256_file(completion_path),
        "COMPLETE does not hash the completion manifest",
    )
    _require(
        complete.get("schema") == "corrected-proportional-n100-complete-v1"
        and completion.get("schema") == "corrected-proportional-n100-completion-v1",
        "completion schema mismatch",
    )
    _require(
        complete.get("completion_manifest_bytes") == completion_path.stat().st_size,
        "COMPLETE completion-manifest byte count mismatch",
    )
    _require(
        complete.get("written_last") is True
        and complete.get("n1000_started") is False
        and completion.get("n1000_started") is False,
        "completion last-write/n1000 contract mismatch",
    )
    artifacts = completion.get("artifacts")
    _require(isinstance(artifacts, dict) and artifacts, "flat completion artifact seal is missing")
    _require("completion_manifest.json" not in artifacts, "completion manifest self-hashes")
    _require("COMPLETE.json" not in artifacts, "COMPLETE self-hashes")
    _require(
        {name for name in artifacts if "/" not in name} == EXPECTED_PRIOR_ROOT_FILES,
        "completion root-artifact inventory is not exact",
    )
    for relative in artifacts:
        if "/" not in relative:
            continue
        parts = Path(relative).parts
        _require(
            len(parts) == 2
            and parts[0] in ("checkpoints", "timing_segments")
            and parts[1].endswith(".json"),
            f"unauthorized signed subdirectory artifact: {relative}",
        )
    for relative, signature in artifacts.items():
        _require(
            isinstance(relative, str)
            and relative
            and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts,
            f"unsafe signed artifact path {relative!r}",
        )
        _require(
            isinstance(signature, dict)
            and set(signature) >= {"bytes", "sha256"},
            f"malformed artifact signature for {relative}",
        )
        path = output / relative
        _require(path.is_file(), f"signed artifact missing: {relative}")
        _require(
            path.stat().st_size == int(signature["bytes"])
            and _sha256_file(path) == signature["sha256"],
            f"signed artifact drift: {relative}",
        )
    actual_files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    expected_files = set(artifacts) | {"completion_manifest.json", "COMPLETE.json"}
    _require(actual_files == expected_files, "final campaign file inventory is not exact")
    expected_directories = {"."}
    for relative in expected_files:
        parent = Path(relative).parent
        while str(parent) not in ("", "."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    actual_directories = {"."} | {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_dir()
    }
    _require(
        actual_directories == expected_directories,
        "final campaign contains an undeclared/temporary directory",
    )

    latest_signed_mtime = max((output / relative).stat().st_mtime_ns for relative in artifacts)
    completion_mtime = completion_path.stat().st_mtime_ns
    complete_mtime = complete_path.stat().st_mtime_ns
    _require(
        completion_mtime >= latest_signed_mtime,
        "completion manifest was not written after all signed artifacts",
    )
    _require(
        complete_mtime >= completion_mtime,
        "COMPLETE.json was not written last",
    )
    _require(
        complete.get("plan_sha256") == completion.get("plan_sha256"),
        "COMPLETE/completion plan hashes differ",
    )
    _require(
        complete.get("status") == completion.get("status"),
        "COMPLETE/completion status mismatch",
    )
    _require(
        completion.get("artifact_count") == len(artifacts)
        and completion.get("completion_manifest_self_signed") is False
        and completion.get("complete_file_self_signed") is False,
        "completion artifact/self-signing metadata mismatch",
    )
    _require(
        completion.get("analysis_sha256") == artifacts["analysis.json"]["sha256"],
        "completion analysis signature mismatch",
    )
    return completion, complete


def _expected_preflight_ids(pairs: Sequence[Mapping[str, Any]]) -> List[str]:
    selected = [
        pair["pair_id"]
        for pair in pairs
        if int(pair["sample_id"]) == 0
        or pair["pair_id"] == "a079_proportional_2tier_p64_k8__s066"
    ]
    _require(len(selected) == 33 and len(set(selected)) == 33, "independent preflight selection drift")
    return selected


def _verify_preflight_seal(
    output: Path,
    checkpoints: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    path = output / "preflight_complete.json"
    seal = _read_json(path)
    expected_ids = _expected_preflight_ids(pairs)
    _require(
        seal.get("schema") == "corrected-proportional-n100-preflight-v1",
        "preflight schema mismatch",
    )
    _require(seal.get("passed") is True, "preflight seal did not pass")
    _require(
        seal.get("status") == "PASS_PREFLIGHT_33_READY_FOR_REMAINING_3167",
        "preflight status mismatch",
    )
    _require(seal.get("pair_count") == 33, "preflight pair count is not 33")
    _require(seal.get("row_count") == 66, "preflight row count is not 66")
    _require(seal.get("ordered_pair_ids") == expected_ids, "preflight pair-ID list mismatch")
    _require(
        seal.get("first_allocator_counts")
        == {ALLOCATORS[0]: 33, ALLOCATORS[1]: 0},
        "preflight allocator-first accounting mismatch",
    )
    _require(
        seal.get("conservation_gate") == {"passed": True, "row_count": 66}
        and seal.get("historical_join_gate") == {"passed": True, "row_count": 66},
        "preflight conservation/historical gate mismatch",
    )
    signatures = seal.get("checkpoint_signatures")
    _require(isinstance(signatures, dict), "preflight checkpoint signatures missing")
    expected_names = {f"checkpoints/{pair_id}.json" for pair_id in expected_ids}
    _require(set(signatures) == expected_names, "preflight checkpoint signature inventory mismatch")
    for relative, signature in signatures.items():
        checkpoint_path = output / relative
        _require(
            checkpoint_path.stat().st_size == int(signature["bytes"])
            and _sha256_file(checkpoint_path) == signature["sha256"],
            f"preflight checkpoint changed after its seal: {relative}",
        )
    timing_signatures = seal.get("timing_segment_signatures")
    _require(
        isinstance(timing_signatures, dict) and timing_signatures,
        "preflight timing signatures are missing",
    )
    timing_coverage: set[str] = set()
    for relative, signature in timing_signatures.items():
        _require(
            relative.startswith("timing_segments/segment_") and relative.endswith(".json"),
            f"invalid preflight timing path: {relative}",
        )
        timing_path = output / relative
        _require(
            timing_path.is_file()
            and timing_path.stat().st_size == int(signature["bytes"])
            and _sha256_file(timing_path) == signature["sha256"],
            f"preflight timing segment changed after its seal: {relative}",
        )
        segment = _read_json(timing_path)
        segment_ids = set(segment.get("pair_ids", []))
        _require(segment_ids and segment_ids <= set(expected_ids), f"preflight timing coverage escaped: {relative}")
        _require(not timing_coverage.intersection(segment_ids), f"duplicate preflight timing coverage: {relative}")
        timing_coverage.update(segment_ids)
    _require(timing_coverage == set(expected_ids), "preflight timing signatures do not cover 33 pairs")
    _require(
        all(pair_id in checkpoints for pair_id in expected_ids),
        "preflight pair missing from final checkpoint inventory",
    )
    odd_pair = next(pair for pair in pairs if pair["execution_order"][0] == ALLOCATORS[1])
    _require(
        seal.get("odd_order_bridge_gate")
        == {
            "passed": True,
            "pair_id": odd_pair["pair_id"],
            "sample_id": int(odd_pair["sample_id"]),
            "execution_order": [ALLOCATORS[1], ALLOCATORS[0]],
            "same_pair_object_delegated": True,
            "simulations_run": 0,
        },
        "preflight odd-order synthetic bridge mismatch",
    )
    overlap_ids = {
        "a069_proportional_3tier_os4_p64_k2__s000",
        "a072_proportional_3tier_os4_p64_k16__s000",
        "a079_proportional_2tier_p64_k8__s000",
        "a079_proportional_2tier_p64_k8__s066",
    }
    _require(
        set(expected_ids) & {
            item["pair_id"] for item in _read_json(AUDIT_V2_EQUIVALENCE)["pairs"]
        }
        == overlap_ids,
        "preflight Audit-v2 overlap is not exactly four pairs",
    )
    v2_gate = seal.get("audit_v2_overlap_gate", {})
    _require(
        v2_gate.get("passed") is True
        and v2_gate.get("pair_count") == 4
        and v2_gate.get("row_count") == 8
        and v2_gate.get("require_all") is False
        and set(v2_gate.get("pair_ids", [])) == overlap_ids,
        "preflight Audit-v2 recorded gate mismatch",
    )
    _require(seal.get("plan_sha256") == manifest.get("plan_sha256"), "preflight plan mismatch")
    _require(
        seal.get("source_gate")
        == {
            "passed": True,
            "immutable_snapshot_sha256": _json_digest(manifest["immutable_before"]),
            "driver_sha256": manifest["driver_sha256"],
        },
        "preflight source gate mismatch",
    )
    seal_mtime = path.stat().st_mtime_ns
    _require(
        all(
            (output / "checkpoints" / f"{pair_id}.json").stat().st_mtime_ns
            <= seal_mtime
            for pair_id in expected_ids
        ),
        "preflight seal predates a preflight checkpoint",
    )
    remaining_ids = set(checkpoints) - set(expected_ids)
    _require(len(remaining_ids) == 3_167, "remaining phase checkpoint count is not 3,167")
    _require(
        all(
            (output / "checkpoints" / f"{pair_id}.json").stat().st_mtime_ns
            >= seal_mtime
            for pair_id in remaining_ids
        ),
        "a remaining-phase checkpoint predates the preflight seal",
    )
    return {
        "pair_count": 33,
        "row_count": 66,
        "audit_v2_overlap_pair_count": 4,
        "pair_ids_sha256": _json_digest(expected_ids),
    }


def _verify_provenance(
    manifest: Mapping[str, Any],
    completion: Mapping[str, Any],
    output: Path,
) -> Dict[str, Any]:
    driver_sha256 = _sha256_file(CAMPAIGN_DRIVER_PATH)
    _require(
        driver_sha256 == EXPECTED_CAMPAIGN_DRIVER_SHA256,
        "campaign driver differs from independently audited version",
    )
    source_sha256 = {
        "sim.py": EXPECTED_SOURCE_HASHES[SIM_PATH],
        "experiments/run_rate_allocator_n100.py": EXPECTED_SOURCE_HASHES[CANONICAL_PATH],
        "experiments/run_rate_allocator_pilot.py": EXPECTED_SOURCE_HASHES[CORE_PATH],
        "investigations/CORRECTED_PROPORTIONAL_N100_SPEC_2026_08_07.md": EXPECTED_SOURCE_HASHES[SPEC_PATH],
    }
    reference_sha256 = {
        "investigations/proportional_mechanism_audit_v2/audit_v2_2026-08-07_01/COMPLETE.json": EXPECTED_SOURCE_HASHES[AUDIT_V2_ROOT / "COMPLETE.json"],
        "investigations/proportional_mechanism_audit/audit_2026-08-07_01/COMPLETE.json": EXPECTED_SOURCE_HASHES[AUDIT_V1_ROOT / "COMPLETE.json"],
        "investigations/rate_allocator_n100/n100_2026-08-06_03/COMPLETE.json": EXPECTED_SOURCE_HASHES[HISTORICAL_ROOT / "COMPLETE.json"],
    }
    _require(Path(manifest.get("output", "")).resolve() == output, "run manifest output mismatch")
    _require(
        manifest.get("schema") == "corrected-proportional-n100-run-v1"
        and isinstance(manifest.get("workers"), int)
        and 1 <= int(manifest["workers"]) <= 8
        and manifest.get("multiprocessing_start_method") == "spawn"
        and manifest.get("execution_phases") == ["preflight_33", "remaining_3167"]
        and manifest.get("historical_outcomes_are_diagnostic_only") is True
        and manifest.get("n1000_execution_path") is False,
        "run manifest execution contract mismatch",
    )
    frozen = _frozen_snapshot()
    results = _snapshot_tree(RESULTS_ROOT)
    immutable = {
        "source_sha256": source_sha256,
        "reference_sha256": reference_sha256,
        "protected_trees": {
            "historical_n100": _protected_tree_snapshot(HISTORICAL_ROOT),
            "audit_v1": _protected_tree_snapshot(AUDIT_V1_ROOT),
            "audit_v2": _protected_tree_snapshot(AUDIT_V2_ROOT),
        },
        "frozen": frozen,
        "results_tree": results,
    }
    _require(manifest.get("immutable_before") == immutable, "immutable trees differ from run-start seal")
    _require(completion.get("immutable_after") == immutable, "immutable trees differ from final seal")
    _require(manifest.get("driver_sha256") == driver_sha256, "run driver hash does not match current source")
    expected_authorization = _json_digest(
        {
            "plan_sha256": manifest.get("plan_sha256"),
            "output": str(output),
            "workers": int(manifest["workers"]),
            "driver_sha256": driver_sha256,
            "immutable_inputs": immutable,
        }
    )
    _require(
        manifest.get("authorization_sha256") == expected_authorization,
        "run authorization digest mismatch",
    )
    unsigned_manifest = dict(manifest)
    recorded_manifest_hash = unsigned_manifest.pop("manifest_payload_sha256", None)
    _require(
        recorded_manifest_hash == _json_digest(unsigned_manifest),
        "run manifest payload self-hash mismatch",
    )
    return {
        "driver_sha256": driver_sha256,
        "immutable": immutable,
        "frozen": frozen,
        "results_tree": results,
        "audit_v2_tree": immutable["protected_trees"]["audit_v2"],
        "audit_v1_tree": immutable["protected_trees"]["audit_v1"],
        "historical_tree": immutable["protected_trees"]["historical_n100"],
    }


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _require(reader.fieldnames is not None, f"CSV header missing: {path.name}")
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames), rows


def _verify_csv_exports(
    output: Path,
    checkpoints: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    independent: Mapping[str, Any],
) -> Dict[str, Any]:
    results_header, result_rows = _read_csv(output / "results_long.csv")
    pairs_header, pair_rows = _read_csv(output / "pairs.csv")
    arm_header, arm_rows = _read_csv(output / "arm_analysis.csv")
    strata_header, strata_rows = _read_csv(output / "strata_analysis.csv")
    _, historical_rows = _read_csv(output / "historical_deltas.csv")
    _, equal_rows = _read_csv(output / "equal_comparison.csv")
    _, loo_rows = _read_csv(output / "leave_one_seed_out.csv")
    _require(len(result_rows) == 6_400, "results_long.csv row count is not 6,400")
    _require(len(pair_rows) == 3_200, "pairs.csv row count is not 3,200")
    _require(len(arm_rows) == 32, "arm_analysis.csv row count is not 32")
    _require(len(strata_rows) == 10, "strata_analysis.csv row count is not 10")
    _require(len(historical_rows) == 6_400, "historical_deltas.csv row count is not 6,400")
    _require(len(equal_rows) == 6_400, "equal_comparison.csv row count is not 6,400")
    _require(len(loo_rows) == 100, "leave_one_seed_out.csv row count is not 100")
    _require(
        {"pair_id", "allocator"} <= set(results_header),
        "results_long.csv lacks pair_id/allocator",
    )
    _require("pair_id" in pairs_header, "pairs.csv lacks pair_id")
    result_keys = [(row["pair_id"], row["allocator"]) for row in result_rows]
    _require(len(set(result_keys)) == 6_400, "results_long.csv keys are not unique")
    expected_result_keys = {
        (pair["pair_id"], allocator) for pair in pairs for allocator in ALLOCATORS
    }
    _require(set(result_keys) == expected_result_keys, "results_long.csv key inventory mismatch")
    pair_ids = [row["pair_id"] for row in pair_rows]
    _require(len(set(pair_ids)) == 3_200, "pairs.csv pair IDs are not unique")
    _require(pair_ids == [pair["pair_id"] for pair in pairs], "pairs.csv canonical order/inventory mismatch")

    # Fields available in the export are checked against checkpoint truth.  The
    # fixed schema is also checked after it lands through these mandatory names.
    mandatory_result_fields = {
        "pair_id",
        "arm_id",
        "sample_id",
        "fabric",
        "ring_size",
        "k",
        "allocator",
        "completion_time_s",
        "completion_time_hex",
        "simulated_ticks",
        "remaining_nonzero_count",
        "remaining_min_B",
        "remaining_max_B",
        "historical_completion_time_hex",
        "historical_simulated_ticks",
        "corrected_minus_historical_ticks",
        "equal_pair_id",
        "equal_completion_time_hex",
        "equal_simulated_ticks",
        "corrected_proportional_minus_equal_ticks",
    }
    _require(
        mandatory_result_fields <= set(results_header),
        f"results_long.csv missing fields: {sorted(mandatory_result_fields - set(results_header))}",
    )
    pair_specs = {pair["pair_id"]: pair for pair in pairs}
    for exported in result_rows:
        pair_id = exported["pair_id"]
        allocator = exported["allocator"]
        pair = pair_specs[pair_id]
        row = _checkpoint_row_map(checkpoints[pair_id])[allocator]
        expected_text = {
            "arm_id": str(pair["config"]["arm_id"]),
            "sample_id": str(pair["sample_id"]),
            "fabric": str(pair["config"]["fabric"]),
            "ring_size": str(pair["config"]["ring_size"]),
            "k": str(pair["config"]["k"]),
            "completion_time_hex": str(row["completion_time_hex"]),
            "simulated_ticks": str(row["simulated_ticks"]),
        }
        for field, wanted in expected_text.items():
            _require(exported[field] == wanted, f"results_long.csv {field} mismatch: {pair_id}/{allocator}")
        _require(
            _f64_hex(float(exported["completion_time_s"])) == row["completion_time_hex"],
            f"results_long.csv completion mismatch: {pair_id}/{allocator}",
        )
        _require(
            exported["remaining_nonzero_count"] == "0"
            and float(exported["remaining_min_B"]) == 0.0
            and float(exported["remaining_max_B"]) == 0.0,
            f"results_long.csv remaining-byte evidence mismatch: {pair_id}/{allocator}",
        )
        historical_diag = row["reference_diagnostics"]["historical_proportional"]
        equal_diag = row["reference_diagnostics"]["matched_equal_policy"]
        for field, wanted in (
            ("historical_completion_time_hex", historical_diag["completion_time_hex"]),
            ("historical_simulated_ticks", historical_diag["simulated_ticks"]),
            (
                "corrected_minus_historical_ticks",
                historical_diag["corrected_minus_historical_ticks"],
            ),
            ("equal_pair_id", equal_diag["pair_id"]),
            ("equal_completion_time_hex", equal_diag["completion_time_hex"]),
            ("equal_simulated_ticks", equal_diag["simulated_ticks"]),
            (
                "corrected_proportional_minus_equal_ticks",
                equal_diag["corrected_proportional_minus_equal_ticks"],
            ),
        ):
            _require(str(exported[field]) == str(wanted), f"results_long.csv {field} mismatch: {pair_id}/{allocator}")
    for name, exported_rows, diagnostic_key in (
        ("historical_deltas.csv", historical_rows, "historical_proportional"),
        ("equal_comparison.csv", equal_rows, "matched_equal_policy"),
    ):
        keys = [(row["pair_id"], row["allocator"]) for row in exported_rows]
        _require(len(set(keys)) == 6_400 and set(keys) == expected_result_keys, f"{name} key inventory mismatch")
        for exported in exported_rows:
            pair_id, allocator = exported["pair_id"], exported["allocator"]
            source_row = _checkpoint_row_map(checkpoints[pair_id])[allocator]
            diag = source_row["reference_diagnostics"][diagnostic_key]
            if diagnostic_key == "historical_proportional":
                expected_values = {
                    "corrected_completion_time_hex": diag["corrected_completion_time_hex"],
                    "corrected_simulated_ticks": diag["corrected_simulated_ticks"],
                    "historical_completion_time_hex": diag["completion_time_hex"],
                    "historical_simulated_ticks": diag["simulated_ticks"],
                    "corrected_minus_historical_ticks": diag["corrected_minus_historical_ticks"],
                }
                numeric_values = {
                    "corrected_completion_time_s": diag["corrected_completion_time_s"],
                    "historical_completion_time_s": diag["completion_time_s"],
                    "corrected_minus_historical_s": diag["corrected_minus_historical_s"],
                    "relative_delta": diag["relative_delta"],
                }
            else:
                expected_values = {
                    "equal_pair_id": diag["pair_id"],
                    "corrected_proportional_time_hex": diag["corrected_completion_time_hex"],
                    "corrected_proportional_ticks": diag["corrected_simulated_ticks"],
                    "equal_time_hex": diag["completion_time_hex"],
                    "equal_ticks": diag["simulated_ticks"],
                    "corrected_proportional_minus_equal_ticks": diag[
                        "corrected_proportional_minus_equal_ticks"
                    ],
                }
                numeric_values = {
                    "corrected_proportional_time_s": diag["corrected_completion_time_s"],
                    "equal_time_s": diag["completion_time_s"],
                    "equal_over_corrected_proportional": diag[
                        "equal_over_corrected_proportional"
                    ],
                    "corrected_proportional_minus_equal_s": diag[
                        "corrected_proportional_minus_equal_s"
                    ],
                }
            for field, wanted in expected_values.items():
                _require(str(exported[field]) == str(wanted), f"{name} {field} mismatch: {pair_id}/{allocator}")
            for field, wanted in numeric_values.items():
                _require(
                    _f64_hex(float(exported[field])) == _f64_hex(wanted),
                    f"{name} {field} mismatch: {pair_id}/{allocator}",
                )
    mandatory_pair_fields = {
        "pair_id",
        "arm_id",
        "sample_id",
        "fabric",
        "ring_size",
        "k",
        "link_local_time_s",
        "network_maxmin_time_s",
        "network_over_link_local",
        "log_network_over_link_local",
        "network_minus_link_local_s",
        "network_minus_link_local_ms",
        "network_minus_link_local_ticks",
        "tick_class",
    }
    _require(
        mandatory_pair_fields <= set(pairs_header),
        f"pairs.csv missing fields: {sorted(mandatory_pair_fields - set(pairs_header))}",
    )
    for exported in pair_rows:
        pair = pair_specs[exported["pair_id"]]
        rows = _checkpoint_row_map(checkpoints[pair["pair_id"]])
        local = rows[ALLOCATORS[0]]
        maxmin = rows[ALLOCATORS[1]]
        ratio = float(maxmin["completion_time_s"]) / float(local["completion_time_s"])
        delta_ticks = int(maxmin["simulated_ticks"]) - int(local["simulated_ticks"])
        _require(
            _f64_hex(float(exported["network_over_link_local"])) == _f64_hex(ratio),
            f"pairs.csv ratio mismatch: {pair['pair_id']}",
        )
        _require(
            int(exported["network_minus_link_local_ticks"]) == delta_ticks,
            f"pairs.csv tick delta mismatch: {pair['pair_id']}",
        )
        _require(
            exported["tick_class"] == _tick_class(delta_ticks),
            f"pairs.csv tick class mismatch: {pair['pair_id']}",
        )
        for field, expected_value in (
            ("link_local_time_s", float(local["completion_time_s"])),
            ("network_maxmin_time_s", float(maxmin["completion_time_s"])),
            ("log_network_over_link_local", math.log(ratio)),
            (
                "network_minus_link_local_s",
                float(maxmin["completion_time_s"]) - float(local["completion_time_s"]),
            ),
        ):
            _require(
                _f64_hex(float(exported[field])) == _f64_hex(expected_value),
                f"pairs.csv {field} mismatch: {pair['pair_id']}",
            )
        _assert_tree_matches(
            float(exported["network_minus_link_local_ms"]),
            1_000.0 * (float(maxmin["completion_time_s"]) - float(local["completion_time_s"])),
            path=f"pairs.csv.{pair['pair_id']}.delta_ms",
        )
    arm_by_id = {row["arm_id"]: row for row in arm_rows}
    _require(set(arm_by_id) == set(independent["per_arm"]), "arm_analysis.csv inventory mismatch")
    for arm_id, expected in independent["per_arm"].items():
        row = arm_by_id[arm_id]
        for field, wanted in (
            ("pair_count", 100),
            ("bootstrap_index_sha256", EXPECTED_BOOTSTRAP_INDEX_SHA256),
            ("faster_2plus", expected["tick_counts"]["maxmin_faster_by_2plus"]),
            ("exact_tie", expected["tick_counts"]["exact_tie"]),
            ("one_tick_tie", expected["tick_counts"]["one_tick_tie"]),
            ("slower_2plus", expected["tick_counts"]["maxmin_slower_by_2plus"]),
        ):
            _require(str(row[field]) == str(wanted), f"arm_analysis.csv {field} mismatch: {arm_id}")
        for field, wanted in (
            ("geometric_mean_ratio", expected["geometric_mean_ratio"]),
            ("ci95_low", expected["ci95_low"]),
            ("ci95_high", expected["ci95_high"]),
        ):
            _assert_tree_matches(float(row[field]), wanted, path=f"arm_analysis.csv.{arm_id}.{field}")
    expected_strata: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for dimension, source_dimension in (("fabric", "fabric"), ("ring_size", "P"), ("k", "k")):
        for value, expected in independent["strata"][source_dimension].items():
            expected_strata[(dimension, value)] = expected
    observed_strata = {(row["dimension"], row["value"]): row for row in strata_rows}
    _require(set(observed_strata) == set(expected_strata), "strata_analysis.csv inventory mismatch")
    for key, expected in expected_strata.items():
        row = observed_strata[key]
        _require(int(row["pair_count"]) == expected["pair_count"], f"strata pair count mismatch: {key}")
        _assert_tree_matches(
            float(row["geometric_mean_ratio"]),
            expected["geometric_mean_ratio"],
            path=f"strata_analysis.csv.{key}.geometric_mean_ratio",
        )
    observed_loo = {int(row["omitted_seed"]): row for row in loo_rows}
    expected_loo = {
        int(row["sample_id"]): float(row["geometric_mean_ratio"])
        for row in independent["leave_one_seed_out"]["values"]
    }
    _require(set(observed_loo) == set(SAMPLE_IDS), "leave_one_seed_out.csv seed inventory mismatch")
    point = float(independent["global"]["point_estimate"])
    for seed, expected_value in expected_loo.items():
        row = observed_loo[seed]
        _assert_tree_matches(
            float(row["geometric_mean_ratio"]),
            expected_value,
            path=f"leave_one_seed_out.csv.{seed}",
        )
        expected_crosses = (point < 1.0 and expected_value >= 1.0) or (
            point > 1.0 and expected_value <= 1.0
        )
        _require(
            row["crosses_one_relative_to_full"] == str(expected_crosses),
            f"leave_one_seed_out.csv crossing flag mismatch: {seed}",
        )
    return {
        "results_long_rows": len(result_rows),
        "pairs_rows": len(pair_rows),
        "arm_analysis_rows": len(arm_rows),
        "strata_analysis_rows": len(strata_rows),
        "historical_delta_rows": len(historical_rows),
        "equal_comparison_rows": len(equal_rows),
        "leave_one_seed_out_rows": len(loo_rows),
        "results_header": results_header,
        "pairs_header": pairs_header,
    }


def _verify_timing_segments(
    output: Path,
    checkpoints: Mapping[str, Mapping[str, Any]],
    preflight_ids: Sequence[str],
) -> Dict[str, Any]:
    root = output / "timing_segments"
    paths = sorted(root.glob("*.json"))
    _require(paths, "timing segment inventory is empty")
    covered: set[str] = set()
    seen_remaining = False
    total_simulation_wall = 0.0
    total_end_to_end_wall = 0.0
    preflight_set = set(preflight_ids)
    for index, path in enumerate(paths, start=1):
        _require(path.name == f"segment_{index:03d}.json", "timing segments are not sequential")
        segment = _read_json(path)
        _require(
            segment.get("schema") == "corrected-proportional-n100-timing-segment-v1"
            and segment.get("segment_index") == index,
            f"timing segment schema/index mismatch: {path.name}",
        )
        pair_ids = list(segment.get("pair_ids", []))
        _require(pair_ids and len(pair_ids) == len(set(pair_ids)), f"invalid timing pair list: {path.name}")
        _require(not covered.intersection(pair_ids), f"timing pair coverage overlaps: {path.name}")
        _require(set(pair_ids) <= set(checkpoints), f"unknown timing pair: {path.name}")
        is_preflight = set(pair_ids) <= preflight_set
        is_remaining = set(pair_ids).isdisjoint(preflight_set)
        _require(is_preflight or is_remaining, f"timing segment mixes execution phases: {path.name}")
        if is_remaining:
            seen_remaining = True
        _require(not (is_preflight and seen_remaining), "preflight timing follows remaining phase")
        _require(
            segment.get("phase")
            in ("preflight_33", "remaining_3167", "recovered_after_interruption"),
            f"unknown timing phase: {path.name}",
        )
        elapsed = _finite(segment.get("elapsed_pool_wall_s"), f"{path.name}: elapsed", positive=True)
        expected_sim = sum(
            float(row["simulation_wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        expected_total = sum(
            float(row["wall_time_s"])
            for pair_id in pair_ids
            for row in checkpoints[pair_id]["rows"]
        )
        _require(
            _f64_hex(segment.get("worker_simulation_wall_sum_s")) == _f64_hex(expected_sim)
            and _f64_hex(segment.get("worker_end_to_end_wall_sum_s")) == _f64_hex(expected_total),
            f"timing worker sums mismatch: {path.name}",
        )
        for pair_id in pair_ids:
            timing = checkpoints[pair_id].get("parent_timing", {})
            _require(timing.get("segment_index") == index, f"checkpoint timing index mismatch: {pair_id}")
            checkpoint_elapsed = _finite(
                timing.get("pool_elapsed_at_checkpoint_s"),
                f"{pair_id}: pool elapsed",
                positive=True,
            )
            _require(checkpoint_elapsed <= elapsed, f"checkpoint elapsed exceeds segment: {pair_id}")
        covered.update(pair_ids)
        total_simulation_wall += expected_sim
        total_end_to_end_wall += expected_total
    _require(covered == set(checkpoints), "timing segments do not cover exactly all 3,200 pairs")
    return {
        "segment_count": len(paths),
        "covered_pair_count": len(covered),
        "worker_simulation_wall_sum_s": total_simulation_wall,
        "worker_end_to_end_wall_sum_s": total_end_to_end_wall,
    }


def _verify_auxiliary_exports(
    output: Path,
    completion: Mapping[str, Any],
    timing: Mapping[str, Any],
) -> Dict[str, Any]:
    gate = _read_json(output / "gate.json")
    _require(gate == completion.get("gate"), "gate.json differs from completion manifest")
    _require(
        gate.get("passed") is True
        and gate.get("pair_count") == 3_200
        and gate.get("row_count") == 6_400
        and gate.get("arm_count") == 32
        and gate.get("per_arm_rows") == 200
        and gate.get("per_seed_rows") == 64
        and gate.get("allocator_rows") == {allocator: 3_200 for allocator in ALLOCATORS}
        and gate.get("allocator_first_pair_counts")
        == {allocator: 1_600 for allocator in ALLOCATORS}
        and gate.get("conservation_rows") == 6_400
        and gate.get("historical_join_rows") == 6_400
        and gate.get("matched_equal_pair_count") == 3_200
        and gate.get("matched_equal_allocator_identical_pairs") == 3_200,
        "global gate cardinality/coverage mismatch",
    )
    v2 = gate.get("audit_v2_overlap_gate", {})
    _require(
        v2.get("passed") is True
        and v2.get("pair_count") == 30
        and v2.get("row_count") == 60
        and v2.get("require_all") is True,
        "global gate Audit-v2 coverage mismatch",
    )
    _require(
        _read_json(output / "v2_overlap.json") == v2,
        "v2_overlap.json differs from the independently checked global gate",
    )
    runtime = _read_json(output / "runtime.json")
    _require(runtime == completion.get("runtime"), "runtime.json differs from completion manifest")
    _require(
        runtime.get("schema") == "corrected-proportional-n100-runtime-v1"
        and runtime.get("timing_segment_count") == timing["segment_count"]
        and runtime.get("n1000_eta_reported") is False
        and runtime.get("historical_linear_estimate_min") == 2.19
        and runtime.get("predeclared_operational_allowance_min") == [3.5, 5.0],
        "runtime provenance contract mismatch",
    )
    _assert_tree_matches(
        runtime.get("worker_simulation_wall_sum_s"),
        timing["worker_simulation_wall_sum_s"],
        path="runtime.worker_simulation_wall_sum_s",
    )
    _assert_tree_matches(
        runtime.get("worker_end_to_end_wall_sum_s"),
        timing["worker_end_to_end_wall_sum_s"],
        path="runtime.worker_end_to_end_wall_sum_s",
    )
    _finite(runtime.get("elapsed_pool_wall_sum_s"), "runtime pool wall", positive=True)
    _finite(runtime.get("completed_pairs_per_pool_second"), "runtime throughput", positive=True)
    return {"gate_passed": True, "runtime_schema": runtime["schema"]}


def _validate_output_path(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    output = candidate.resolve()
    _require(
        output != CAMPAIGN_ROOT and CAMPAIGN_ROOT in output.parents,
        f"output must be a child of {CAMPAIGN_ROOT}",
    )
    _require(output.is_dir(), f"campaign output directory does not exist: {output}")
    return output


def _self_test() -> Dict[str, Any]:
    sources = _verify_source_seals()
    _verify_reference_statuses()
    inventory_contract = _driver_root_inventory_contract()
    _require(
        inventory_contract["prior"] == EXPECTED_PRIOR_ROOT_FILES,
        "auditor/driver prior-final root allowlists differ",
    )
    _require(
        inventory_contract["final"]
        == EXPECTED_PRIOR_ROOT_FILES | {"completion_manifest.json", "COMPLETE.json"},
        "driver final root allowlist differs from the independently expected set",
    )
    _require(
        {"prior_final", "final"} <= inventory_contract["enforced_modes"],
        "driver does not enforce both prior-final and final root inventories",
    )
    canonical_slice = _canonical_slice()
    _, bootstrap = _bootstrap_index_matrix(100)
    _require(
        bootstrap["bootstrap_index_sha256"] == EXPECTED_BOOTSTRAP_INDEX_SHA256,
        "self-test bootstrap digest mismatch",
    )
    expected_classes = {
        -3: "maxmin_faster_by_2plus",
        -2: "maxmin_faster_by_2plus",
        -1: "one_tick_tie",
        0: "exact_tie",
        1: "one_tick_tie",
        2: "maxmin_slower_by_2plus",
        3: "maxmin_slower_by_2plus",
    }
    _require(
        {value: _tick_class(value) for value in expected_classes} == expected_classes,
        "self-test tick classifier mismatch",
    )
    return {
        "status": "PASS_SELF_TEST_NO_SIMULATION",
        "source_count": len(sources),
        "arm_count": len(canonical_slice["arms"]),
        "pair_count": len(canonical_slice["pairs"]),
        "pair_id_sha256": _json_digest(canonical_slice["pair_ids"]),
        "bootstrap_index_sha256": bootstrap["bootstrap_index_sha256"],
        "prior_root_file_count": len(inventory_contract["prior"]),
        "final_root_file_count": len(inventory_contract["final"]),
        "same_handle_lock_signing": inventory_contract["same_handle_lock_signing"],
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independent read-only audit of corrected proportional n=100 artifacts"
    )
    parser.add_argument("--output", help="completed campaign output directory")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="check deterministic helpers and immutable constants; never run a simulation",
    )
    arguments = parser.parse_args(argv)
    if not arguments.self_test and not arguments.output:
        parser.error("--output is required unless --self-test is selected")
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    try:
        if arguments.self_test:
            report = _self_test()
        else:
            # The completed-campaign orchestration is deliberately below all
            # independent primitives so it cannot accidentally call a driver
            # verifier or analysis helper.
            output = _validate_output_path(arguments.output)
            source_seals = _verify_source_seals()
            _verify_reference_statuses()
            reference_bundles = {
                "audit_v1": _verify_signed_reference_bundle(AUDIT_V1_ROOT, kind="audit_v2"),
                "audit_v2": _verify_signed_reference_bundle(AUDIT_V2_ROOT, kind="audit_v2"),
                "historical": _verify_signed_reference_bundle(HISTORICAL_ROOT, kind="historical"),
            }
            completion, complete = _verify_completion_bundle(output)
            manifest = _read_json(output / "run_manifest.json")
            canonical_slice = _canonical_slice()
            _verify_run_plan(manifest, canonical_slice)
            _require(
                completion.get("plan_sha256") == manifest.get("plan_sha256"),
                "completion/run plan hashes differ",
            )
            _require(
                completion.get("pair_count") == 3_200
                and completion.get("simulation_count") == 6_400,
                "completion cardinality mismatch",
            )
            checkpoints = _load_campaign_checkpoints(
                output,
                canonical_slice["pairs"],
                str(manifest["plan_sha256"]),
            )
            preflight = _verify_preflight_seal(
                output, checkpoints, canonical_slice["pairs"], manifest
            )
            timing = _verify_timing_segments(
                output, checkpoints, _expected_preflight_ids(canonical_slice["pairs"])
            )
            historical = _historical_comparison(checkpoints, canonical_slice["pairs"])
            v2 = _audit_v2_overlap(checkpoints)
            equal = _equal_comparison(
                checkpoints,
                canonical_slice["pairs"],
                canonical_slice["full"],
            )
            analysis = _scientific_analysis(
                checkpoints, canonical_slice["pairs"], historical, equal
            )
            csv_exports = _verify_csv_exports(
                output, checkpoints, canonical_slice["pairs"], analysis
            )
            auxiliary = _verify_auxiliary_exports(output, completion, timing)
            provenance = _verify_provenance(manifest, completion, output)
            recorded_analysis = _read_json(output / "analysis.json")
            # Exact schema routing is finalized with the driver artifact patch;
            # the independently computed blocks must be present verbatim modulo
            # tight decimal serialization tolerance.
            _verify_analysis_export(recorded_analysis, analysis, checkpoints)
            _require(
                complete.get("decision", complete.get("status")) == analysis["decision"],
                "COMPLETE decision does not match independent stopping rule",
            )
            markdown = (output / "REPORT.md").read_text(encoding="utf-8")
            _require(
                analysis["decision"] in markdown,
                "REPORT.md omits the audited decision",
            )
            report = {
                "status": "PASS_INDEPENDENT_CORRECTED_PROPORTIONAL_N100_AUDIT",
                "decision": analysis["decision"],
                "output": str(output),
                "inventory": {
                    "signed_artifact_count": len(completion["artifacts"]),
                    "pair_count": len(checkpoints),
                    "row_count": 6_400,
                },
                "preflight": preflight,
                "timing": timing,
                "audit_v2": v2,
                "historical": {
                    key: value
                    for key, value in historical.items()
                    if key != "material_reversal_pair_ids"
                },
                "equal": {
                    "pair_count": equal["pair_count"],
                    "row_count": equal["row_count"],
                    "claim_trigger_count": equal["claim_trigger_count"],
                },
                "global": analysis["global"],
                "leave_one_seed_out": analysis["leave_one_seed_out"],
                "review_reasons": analysis["review_reasons"],
                "csv_exports": csv_exports,
                "auxiliary_exports": auxiliary,
                "source_seal_count": len(source_seals),
                "reference_bundles": {
                    key: {"file_count": value["file_count"], "complete_sha256": value["complete_sha256"]}
                    for key, value in reference_bundles.items()
                },
                "protected_tree_roots": {
                    key: value["root_sha256"]
                    for key, value in provenance["immutable"]["protected_trees"].items()
                },
            }
    except Exception as exc:
        failure = {
            "status": "FAIL_INDEPENDENT_CORRECTED_PROPORTIONAL_N100_AUDIT",
            "decision": "STOP_AND_FIX_N100_INTEGRITY_FAILURE",
            "error": str(exc),
        }
        print(json.dumps(failure, indent=2, sort_keys=True, ensure_ascii=False))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
