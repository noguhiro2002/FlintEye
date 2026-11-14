from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
from typing import Any

from flinteye_app.orchestrator_auth import generate_session_secret, hash_password
from flinteye_app.orchestrator_store import runtime_file_lock, write_private_runtime_json


def _load_runtime(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_runtime(path: Path, data: dict[str, Any]) -> None:
    write_private_runtime_json(path, data, sort_keys=False, ensure_ascii=True)


def _prompt_password(prompt: str) -> str:
    password = getpass.getpass(prompt)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("passwords do not match")
    if not password:
        raise SystemExit("password must not be empty")
    return password


def _ensure_auth_tree(runtime: dict[str, Any]) -> dict[str, Any]:
    auth = runtime.setdefault("auth", {})
    local = auth.setdefault("local", {})
    local.setdefault("admin", {"username": "admin", "password_hash": ""})
    local.setdefault("viewer", {"username": "viewer", "password_hash": ""})
    return auth


def cmd_hash_password(_: argparse.Namespace) -> int:
    password = _prompt_password("Password: ")
    print(hash_password(password))
    return 0


def cmd_init_local(args: argparse.Namespace) -> int:
    runtime_path = Path(args.runtime_file)
    admin_hash = hash_password(_prompt_password(f"Admin password ({args.admin_username}): "))
    viewer_hash = "" if args.viewer_public else hash_password(_prompt_password(f"Viewer password ({args.viewer_username}): "))
    with runtime_file_lock(runtime_path):
        runtime = _load_runtime(runtime_path)
        auth = _ensure_auth_tree(runtime)
        auth["provider"] = "local"
        auth["viewer_auth_required"] = not args.viewer_public
        auth["session_cookie_name"] = auth.get("session_cookie_name") or "orch_session"
        auth["session_ttl_sec"] = int(auth.get("session_ttl_sec") or 43200)
        auth["session_secret"] = generate_session_secret()
        auth["local"]["admin"] = {"username": args.admin_username, "password_hash": admin_hash}
        auth["local"]["viewer"] = {"username": args.viewer_username, "password_hash": viewer_hash}
        _save_runtime(runtime_path, runtime)
    print(f"initialized local auth in {runtime_path}")
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    runtime_path = Path(args.runtime_file)
    password_hash = hash_password(_prompt_password(f"New {args.role} password: "))
    with runtime_file_lock(runtime_path):
        runtime = _load_runtime(runtime_path)
        auth = _ensure_auth_tree(runtime)
        auth["provider"] = auth.get("provider") or "local"
        auth["session_secret"] = generate_session_secret()
        role_block = auth["local"].setdefault(args.role, {})
        if args.username:
            role_block["username"] = args.username
        elif not role_block.get("username"):
            role_block["username"] = args.role
        role_block["password_hash"] = password_hash
        _save_runtime(runtime_path, runtime)
    print(f"updated {args.role} password in {runtime_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local auth settings for the orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    hash_parser = sub.add_parser("hash-password", help="Print a password hash")
    hash_parser.set_defaults(func=cmd_hash_password)

    init_parser = sub.add_parser("init-local", help="Initialize local auth in runtime.json")
    init_parser.add_argument("--runtime-file", default="runtime.json")
    init_parser.add_argument("--admin-username", default="admin")
    init_parser.add_argument("--viewer-username", default="viewer")
    init_parser.add_argument("--viewer-public", action="store_true", help="Do not require viewer login")
    init_parser.set_defaults(func=cmd_init_local)

    set_parser = sub.add_parser("set-password", help="Set one local auth password in runtime.json")
    set_parser.add_argument("--runtime-file", default="runtime.json")
    set_parser.add_argument("--role", choices=["admin", "viewer"], required=True)
    set_parser.add_argument("--username", default="")
    set_parser.set_defaults(func=cmd_set_password)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
