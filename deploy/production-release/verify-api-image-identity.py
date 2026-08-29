from __future__ import annotations

import argparse
import re
import sys


EXIT_PREFLIGHT = 10
EXIT_DEPLOY = 40
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^ddrec-license-api:[A-Za-z0-9_.-]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the deployed API image identity")
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--compose-image", required=True)
    parser.add_argument("--running-image", required=True)
    parser.add_argument("--running-image-id", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--oci-revision", required=True)
    parser.add_argument("--expected-commit", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    values = {
        "EXPECTED_IMAGE": args.expected_image.strip(),
        "COMPOSE_RESOLVED_IMAGE": args.compose_image.strip(),
        "RUNNING_CONTAINER_IMAGE": args.running_image.strip(),
        "RUNNING_IMAGE_ID": args.running_image_id.strip().lower(),
        "EXPECTED_IMAGE_ID": args.expected_image_id.strip().lower(),
        "OCI_REVISION": args.oci_revision.strip().lower(),
        "EXPECTED_HEAD": args.expected_commit.strip().lower(),
    }
    for name, value in values.items():
        print(f"{name}={value}")

    if not IMAGE_RE.fullmatch(values["EXPECTED_IMAGE"]):
        print("DEPLOY_IDENTITY=FAIL reason=invalid-expected-image-reference")
        return EXIT_PREFLIGHT
    if not IMAGE_ID_RE.fullmatch(values["RUNNING_IMAGE_ID"]):
        print("DEPLOY_IDENTITY=FAIL reason=invalid-running-image-id")
        return EXIT_PREFLIGHT
    if not IMAGE_ID_RE.fullmatch(values["EXPECTED_IMAGE_ID"]):
        print("DEPLOY_IDENTITY=FAIL reason=invalid-expected-image-id")
        return EXIT_PREFLIGHT
    if not COMMIT_RE.fullmatch(values["EXPECTED_HEAD"]):
        print("DEPLOY_IDENTITY=FAIL reason=invalid-expected-commit")
        return EXIT_PREFLIGHT

    mismatches: list[str] = []
    if values["COMPOSE_RESOLVED_IMAGE"] != values["EXPECTED_IMAGE"]:
        mismatches.append("compose-image")
    if values["RUNNING_CONTAINER_IMAGE"] != values["EXPECTED_IMAGE"]:
        mismatches.append("running-image")
    if values["RUNNING_IMAGE_ID"] != values["EXPECTED_IMAGE_ID"]:
        mismatches.append("image-id")
    if values["OCI_REVISION"] != values["EXPECTED_HEAD"]:
        mismatches.append("oci-revision")
    if mismatches:
        print(f"DEPLOY_IDENTITY=FAIL reason={','.join(mismatches)}")
        return EXIT_DEPLOY

    print("DEPLOY_IDENTITY=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
