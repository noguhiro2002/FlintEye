"""Run the same required distribution checks locally and in GitHub Actions."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
GROUPS = (
    "backend", "documentation", "frontend", "settings", "browsers", "dependency-audit", "containers",
)
CROSS_BROWSER_TESTS = ("monitoring", "setup", "recordings", "config-revision", "dialog", "navigation", "preview10")
SHELL_SCRIPTS = ("packaging/install.sh", "packaging/build_vendor.sh", "packaging/smoke_bundle.sh")
PREVIOUS_IMAGE = "ghcr.io/noguhiro2002/flinteye:1.2.0-preview.3@sha256:445d6a85dc9c5129213ddd753b13d467a1bdc4464e307fd726f001e525b832f4"


def run(*command, cwd=ROOT, env=None, stdin=None):
    subprocess.run(command, cwd=cwd, env=env, stdin=stdin, check=True)


def run_python(*arguments):
    run(sys.executable, *arguments)


def git_output(*arguments):
    return subprocess.check_output(("git", *arguments), cwd=ROOT)


def check_frontend():
    before = git_output("diff", "--binary", "HEAD", "--", "frontend")
    run("npm", "run", "build", cwd=FRONTEND)
    if before != git_output("diff", "--binary", "HEAD", "--", "frontend"):
        raise ValueError("The production build modified tracked frontend sources.")
    run("npm", "test", cwd=FRONTEND, env={**os.environ, "FLINTEYE_BROWSER": "chromium"})


def check_containers():
    revision = git_output("rev-parse", "HEAD").decode().strip()
    image = "flinteye:check"
    cache = os.environ.get("FLINTEYE_VENDOR_CACHE")
    build_context = ("--build-context", f"vendor-downloads={cache}") if cache else ()
    run("docker", "build", *build_context, "--build-arg", f"FLINTEYE_REVISION={revision}", "-t", image, ".")
    for script, options, arguments in (
        ("smoke_container.py", ["--tmpfs", "/data:rw,uid=10001,gid=10001"], []),
        ("smoke_private_input.py", [], ["--mediamtx", "/opt/flinteye/bin/mediamtx"]),
        ("smoke_storage_faults.py", ["--tmpfs", "/qa-recordings:rw,size=8m,uid=10001,gid=10001"], []),
    ):
        with (ROOT / "packaging" / script).open("rb") as source:
            run("docker", "run", "--rm", "-i", "--network", "none", *options,
                "--entrypoint", "python", image, "-", *arguments, stdin=source)
    run_python("packaging/smoke_compose.py", "--image", image, "--previous-image", PREVIOUS_IMAGE)


def check_group(group):
    if group == "backend":
        run_python("tools/audit_api_coverage.py", "--require-all-operations", "--require-permitted-behavior",
                   "--output", "dist/api-coverage-audit")
    elif group == "documentation":
        run_python("packaging/check_docs.py")
        for script in SHELL_SCRIPTS:
            run("bash", "-n", script)
    elif group == "frontend":
        check_frontend()
    elif group == "settings":
        run("node", "tests/settings-inventory.mjs", cwd=FRONTEND)
        run_python("packaging/qa_settings.py", "dist/settings-coverage")
    elif group == "browsers":
        for engine in ("firefox", "webkit"):
            for test in CROSS_BROWSER_TESTS:
                run("node", f"tests/{test}.mjs", cwd=FRONTEND, env={**os.environ, "FLINTEYE_BROWSER": engine})
    elif group == "dependency-audit":
        run("npm", "run", "audit", cwd=FRONTEND)
    elif group == "containers":
        check_containers()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--group", choices=GROUPS, help="Run one group for a targeted rerun")
    options.add_argument("--list", action="store_true", help="List every required verification group")
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(GROUPS))
        return 0
    groups = (args.group,) if args.group else GROUPS
    for index, group in enumerate(groups):
        print(f"\nRunning {group}", flush=True)
        try:
            check_group(group)
        except (subprocess.CalledProcessError, OSError, ValueError) as error:
            print(f"{group} failed. {error}", file=sys.stderr)
            if remaining := groups[index + 1:]:
                print("Pending groups: " + ", ".join(remaining), file=sys.stderr)
            return 1
        print(f"{group} passed", flush=True)
    if args.group:
        print("Targeted check finished. Run without --group for all required checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
