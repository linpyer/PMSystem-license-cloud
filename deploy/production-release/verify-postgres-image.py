#!/usr/bin/env python3
"""Fail-closed PostgreSQL image reference guard for application releases."""

import argparse
import re
import sys


EXIT_VERIFY = 10
EXIT_CHANGED = 40
IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,510}[A-Za-z0-9]$")


def normalize_image_reference(raw):
    if raw is None:
        raise ValueError("value is missing")
    value = raw.strip()
    if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
        value = value[1:-1].strip()
    if not value:
        raise ValueError("value is empty")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("value contains whitespace or control characters")
    if not IMAGE_REFERENCE.fullmatch(value):
        raise ValueError("value is not a safe image reference")
    return value


def describe(label, raw, normalized=None):
    print("{}RawLength={}".format(label, len(raw)))
    print("{}RawHex={}".format(label, raw.encode("utf-8").hex()))
    if normalized is not None:
        print("{}Reference={}".format(label, normalized))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--current-image-id", required=True)
    parser.add_argument("--current-repo-digests", default="[]")
    args = parser.parse_args()

    current = target = None
    current_error = target_error = None
    try:
        current = normalize_image_reference(args.current)
    except ValueError as exc:
        current_error = str(exc)
    try:
        target = normalize_image_reference(args.target)
    except ValueError as exc:
        target_error = str(exc)

    describe("Current", args.current, current)
    describe("Target", args.target, target)
    print("CurrentImageId={}".format(args.current_image_id))
    print("CurrentRepoDigests={}".format(args.current_repo_digests))

    if current_error or target_error:
        if current_error:
            print("CurrentParseError={}".format(current_error))
        if target_error:
            print("TargetParseError={}".format(target_error))
        print("ERROR: Unable to verify PostgreSQL image identity")
        return EXIT_VERIFY

    if current != target:
        print("ERROR: PostgreSQL image change prohibited")
        print("CurrentReference: {}".format(current))
        print("TargetReference: {}".format(target))
        print("CurrentImageId: {}".format(args.current_image_id))
        print("Normal application releases must not upgrade PostgreSQL images.")
        return EXIT_CHANGED

    print("PostgreSQLImageCheck=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
