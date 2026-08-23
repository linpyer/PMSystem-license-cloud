#!/usr/bin/env python3
"""Audit only Alembic revisions pending between the database revision and head."""

import argparse
import ast
import os
import re
import sys


def assignment_value(tree, name):
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            return ast.literal_eval(value)
    raise ValueError("missing {}".format(name))


def load_revisions(versions_root):
    revisions = {}
    for file_name in sorted(os.listdir(versions_root)):
        if not file_name.endswith(".py") or file_name.startswith("__"):
            continue
        path = os.path.join(versions_root, file_name)
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        revision = assignment_value(tree, "revision")
        down_revision = assignment_value(tree, "down_revision")
        parents = [] if down_revision is None else list(down_revision if isinstance(down_revision, tuple) else (down_revision,))
        if revision in revisions:
            raise ValueError("duplicate revision {}".format(revision))
        revisions[revision] = {"path": path, "parents": parents, "tree": tree}
    if not revisions:
        raise ValueError("no Alembic revisions found")
    return revisions


def ancestors(revisions, starts):
    result = set()
    stack = list(starts)
    while stack:
        revision = stack.pop()
        if not revision or revision in result:
            continue
        if revision not in revisions:
            raise ValueError("revision not found: {}".format(revision))
        result.add(revision)
        stack.extend(revisions[revision]["parents"])
    return result


def pending_revisions(revisions, current, head):
    referenced = set(parent for item in revisions.values() for parent in item["parents"] if parent)
    heads = sorted(set(revisions) - referenced)
    if heads != [head]:
        raise ValueError("package Alembic heads {} do not match expected head {}".format(",".join(heads), head))
    head_history = ancestors(revisions, [head])
    applied = set() if current in ("", "base", "None") else ancestors(revisions, [current])
    pending = head_history - applied
    ordered = []
    remaining = set(pending)
    while remaining:
        ready = sorted(revision for revision in remaining if not (set(revisions[revision]["parents"]) & remaining))
        if not ready:
            raise ValueError("migration graph contains a cycle")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def string_literals(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Str):
            yield child.s
        elif hasattr(ast, "Constant") and isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def audit_upgrade(revision, item):
    upgrade = next((node for node in item["tree"].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "upgrade"), None)
    if upgrade is None:
        return [(1, "MISSING_UPGRADE")]
    findings = []
    dangerous_calls = {
        "drop_table": "DROP_TABLE",
        "drop_column": "DROP_COLUMN",
        "drop_constraint": "DROP_CONSTRAINT",
        "alter_column": "ALTER_COLUMN_REQUIRES_AUDIT",
        "rename_table": "RENAME_TABLE_REQUIRES_AUDIT",
    }
    raw_pattern = re.compile(r"\b(DROP\s+(TABLE|COLUMN)|TRUNCATE\s+|DELETE\s+FROM|ALTER\s+TABLE)\b", re.IGNORECASE)
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call):
            continue
        attribute = node.func.attr if isinstance(node.func, ast.Attribute) else ""
        if attribute in dangerous_calls:
            findings.append((getattr(node, "lineno", 1), dangerous_calls[attribute]))
        if attribute == "execute":
            for value in string_literals(node):
                match = raw_pattern.search(value)
                if match:
                    findings.append((getattr(node, "lineno", 1), "RAW_SQL_{}".format(match.group(1).upper().replace(" ", "_"))))
    return sorted(set(findings))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        revisions = load_revisions(args.versions)
        pending = pending_revisions(revisions, args.current, args.head)
        print("pending={}".format(len(pending)))
        findings = []
        for revision in pending:
            path = revisions[revision]["path"]
            print("pendingRevision={} file={}".format(revision, path))
            for line, rule in audit_upgrade(revision, revisions[revision]):
                findings.append((path, line, rule))
        for path, line, rule in findings:
            print("destructive={} line={} rule={}".format(path, line, rule), file=sys.stderr)
        return 50 if findings else 0
    except Exception as exc:
        print("migration audit error: {}".format(exc), file=sys.stderr)
        return 10


if __name__ == "__main__":
    sys.exit(main())
