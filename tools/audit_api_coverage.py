"""Inventory production API operations and measure the existing unittest suite.

Requires application/test dependencies and coverage.py. This measures execution,
not assertion completeness. Installed-server/browser tests are separate evidence.
Request bodies, headers, raw URLs and response contents are never recorded.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
API_SOURCES = ("flinteye_app/orchestrator_api.py", "flinteye_app/flinteye_routes.py")


def declared_operations():
    """Check the runtime inventory against every literal production decorator."""
    operations = set()
    for filename in API_SOURCES:
        for node in ast.walk(ast.parse((ROOT / filename).read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if ast.unparse(decorator.func.value) != "app":
                    continue
                verb = decorator.func.attr
                if verb not in {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}:
                    continue
                path = ast.literal_eval(decorator.args[0])
                methods = [verb.upper()] if verb != "api_route" else ast.literal_eval(
                    next(item.value for item in decorator.keywords if item.arg == "methods")
                )
                operations.update((method, path) for method in methods)
    return operations


def error_sites(coverage_data, observations):
    """Explicit raises only; implicit framework errors and response returns differ."""
    errors = []
    for path in sorted((ROOT / "flinteye_app").rglob("*.py")):
        filename = str(path.relative_to(ROOT))
        executed = set(coverage_data.lines(str(path)) or [])

        def visit(node, parents=()):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                parents += (node.name,)
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                call = node.exc
                if ast.unparse(call.func).endswith("HTTPException"):
                    status = next((item.value for item in call.keywords if item.arg == "status_code"),
                                  call.args[0] if call.args else None)
                    detail = next((item.value for item in call.keywords if item.arg == "detail"),
                                  call.args[1] if len(call.args) > 1 else None)
                    hits = [item for item in observations if item["file"] == filename
                            and node.lineno <= item["line"] <= node.end_lineno]
                    errors.append({
                        "file": filename, "line": node.lineno, "function": ".".join(parents),
                        "status": status.value if isinstance(status, ast.Constant)
                        and isinstance(status.value, int) else None,
                        "status_expression": ast.unparse(status) if status is not None else "<dynamic>",
                        "detail_expression": ast.unparse(detail) if detail is not None else "",
                        "raise_line_executed": node.lineno in executed,
                        "observed_statuses": sorted({item["status"] for item in hits}),
                        "tests": sorted({item["test"] for item in hits}),
                    })
            for child in ast.iter_child_nodes(node):
                visit(child, parents)

        visit(ast.parse(path.read_text()))
    return errors


def real_http_references(operations):
    """Locate calls in real-server CI scripts; a reference is not execution proof."""
    for item in operations:
        item["real_http_script_references"] = []

    def candidate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return candidate(node.left) + candidate(node.right)
        if isinstance(node, ast.JoinedStr):
            return "".join(candidate(part) if isinstance(part, ast.Constant) else "audit-value"
                           for part in node.values)
        return "audit-value"

    def add(filename, line, method, path):
        prefix = next((value for value in ("/api/v1/", "/media/") if value in path), None)
        if prefix is None:
            return
        path = path[path.index(prefix):]
        for item in operations:
            # Escape literal path components; only declared parameters are wildcards.
            parts = re.split(r"(\{[^}]+\})", item["path"])
            pattern = "".join(".*" if ":path}" in part else "[^/]+" if part.startswith("{")
                              else re.escape(part) for part in parts)
            if item["method"] == method and re.fullmatch(pattern, path):
                entry = {"file": filename, "line": line}
                if entry not in item["real_http_script_references"]:
                    item["real_http_script_references"].append(entry)

    sources = ["packaging/smoke_container.py", "packaging/smoke_desktop_bundle.py",
               "packaging/smoke_compose.py", "packaging/lifecycle_common.py"]
    for filename in sources:
        for node in ast.walk(ast.parse((ROOT / filename).read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args \
                    and node.func.attr in {"get", "post", "put", "patch", "delete", "head", "options"}:
                add(filename, node.lineno, node.func.attr.upper(), candidate(node.args[0]))
    filename = "frontend/tests/installed.mjs"
    for number, line in enumerate((ROOT / filename).read_text().splitlines(), 1):
        for match in re.finditer(r"\b(?:json|api)\('(/api/v1/[^']+)'", line):
            add(filename, number, "GET", match[1])
        for match in re.finditer(r"\.request\.(get|post|patch|put|delete)\(new URL\('(/api/v1/[^']+)'", line):
            add(filename, number, match[1].upper(), match[2])
    for filename in ("packaging/smoke_bundle.sh", "packaging/smoke_windows_installer.ps1"):
        for number, line in enumerate((ROOT / filename).read_text().splitlines(), 1):
            match = re.search(r"/api/v1/[a-z/-]+", line)
            if match:
                verb = re.search(r"-X\s+(GET|POST|PUT|PATCH|DELETE)", line)
                method = verb[1] if verb else "POST" if "--data" in line else "GET"
                add(filename, number, method, match[0])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/api-coverage-audit")
    parser.add_argument("--browser-evidence", type=Path, action="append", default=[],
                        help="Optional passed installed.mjs browser.json; requests only, no status evidence")
    parser.add_argument("--require-all-operations", action="store_true",
                        help="Fail if any registered operation has no HTTP response in the test run")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    try:
        import coverage
    except ImportError:
        parser.error("Install coverage.py in the test environment (validated with coverage==7.17.3)")
    from fastapi import FastAPI, HTTPException
    from fastapi.routing import APIRoute
    from starlette.routing import Mount, Route

    run = coverage.Coverage(source=[str(ROOT / "flinteye_app")], branch=True,
                            data_file=str(args.output / ".coverage"), concurrency=["thread"])
    # The C tracer supports per-test contexts on Python 3.14 as well as 3.13.
    run.set_option("run:core", "ctrace")
    current_test = "<discovery>"
    requests, exceptions = [], []
    lock = threading.Lock()
    original_call, original_exception = FastAPI.__call__, HTTPException.__init__

    def observed_exception(self, *values, **keywords):
        original_exception(self, *values, **keywords)
        caller = sys._getframe(1)
        path = Path(caller.f_code.co_filename).resolve()
        if path.is_relative_to(ROOT / "flinteye_app"):
            with lock:
                exceptions.append({"file": str(path.relative_to(ROOT)), "line": caller.f_lineno,
                                   "status": self.status_code, "test": current_test})

    async def observed_call(self, scope, receive, send):
        if scope["type"] != "http":
            return await original_call(self, scope, receive, send)
        status, error, test = None, None, current_test

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            return await original_call(self, scope, receive, observed_send)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            route = scope.get("route")
            matched = route if isinstance(route, APIRoute) else next(
                (item for item in self.routes if isinstance(item, APIRoute)
                 and scope["method"] in item.methods and item.path_regex.fullmatch(scope["path"])), None)
            if matched is not None and matched.endpoint.__module__.startswith("flinteye_app."):
                with lock:
                    requests.append({
                        "test": test, "method": scope["method"], "path": matched.path,
                        "status": status, "exception": error,
                        "reached_router": isinstance(route, APIRoute),
                        "handler": matched.endpoint.__qualname__,
                        "dependency_overrides": sorted(getattr(item, "__name__", str(item))
                                                       for item in self.dependency_overrides),
                    })

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            nonlocal current_test
            current_test = test.id()
            run.switch_context(current_test)
            super().startTest(test)

        def stopTest(self, test):
            nonlocal current_test
            super().stopTest(test)
            current_test = "<between-tests>"
            run.switch_context(current_test)

    run.start()
    try:
        with patch.object(FastAPI, "__call__", observed_call), patch.object(HTTPException, "__init__", observed_exception):
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
            result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    finally:
        run.stop()
        run.save()
    run.json_report(outfile=str(args.output / "line-branch-coverage.json"), show_contexts=True)

    # Inspect the actual route objects without starting the server or lifespan.
    from flinteye_app import orchestrator_api as api
    from flinteye_app.cli import initialize
    from flinteye_app.flinteye_routes import install_routes

    with tempfile.TemporaryDirectory(prefix="flinteye-api-inventory-") as directory, \
            patch("flinteye_app.orchestrator_logging.LogManager.configure"):
        context = api.AppContext(env_file="", runtime_file=str(initialize(Path(directory))), no_env=True)
        try:
            extension = FastAPI()
            extension.state.context = context
            install_routes(extension, context, setup_token="audit-only-token", desktop=False)
            # Avoid include_router: recent FastAPI versions expose a lazy wrapper.
            registered = [*api.app.routes, *extension.routes]
            for item in registered:
                if isinstance(item, APIRoute):
                    continue
                if type(item) is Route and item.path in {
                    "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"
                }:
                    continue
                if isinstance(item, Mount) and item.name == "ui":
                    continue
                raise RuntimeError("Unrecognized or nested route registration; expand the inventory before auditing")
            routes = [item for item in registered if isinstance(item, APIRoute)]
            generated_documentation = [
                {"path": item.path, "methods": sorted(item.methods)} for item in api.app.routes
                if not isinstance(item, APIRoute) and getattr(item, "methods", None)
            ]
            inventory = []
            for route in routes:
                filename = Path(inspect.getsourcefile(route.endpoint)).resolve()
                _, line = inspect.getsourcelines(route.endpoint)
                for method in sorted(route.methods):
                    hits = [item for item in requests if item["method"] == method and item["path"] == route.path]
                    inventory.append({
                        "method": method, "path": route.path, "file": str(filename.relative_to(ROOT)),
                        "line": line, "handler": route.endpoint.__qualname__,
                        "dependencies": sorted({item.call.__name__ for item in route.dependant.dependencies}),
                        "observed_statuses": sorted({item["status"] for item in hits if item["status"] is not None}),
                        "request_count": len(hits), "tests": sorted({item["test"] for item in hits}),
                    })
            actual = {(item["method"], item["path"]) for item in inventory}
            if actual != declared_operations() or len(actual) != len(inventory):
                raise RuntimeError("Runtime/decorator API inventories differ; audit cannot claim a complete inventory")
            browser_evidence = []
            for path in args.browser_evidence:
                data = json.loads(path.read_text())
                if data["result"] != "passed" or data["apiMocked"] is not False:
                    raise ValueError("Browser evidence must be a passed test against a real API")
                observed = set()
                for entry in data["realApiRequests"]:
                    method, pathname = entry.split(" ", 1)
                    for route in routes:
                        if method in route.methods and route.path_regex.fullmatch(pathname):
                            observed.add((method, route.path))
                browser_evidence.append({"file": str(path), "identity": data["identity"],
                                         "operations": sorted(method + " " + path for method, path in observed)})
            for item in inventory:
                item["ci_browser_request_evidence"] = [evidence["file"] for evidence in browser_evidence
                    if item["method"] + " " + item["path"] in evidence["operations"]]
        finally:
            context.shutdown()

    inventory.sort(key=lambda item: (item["path"], item["method"]))
    real_http_references(inventory)
    errors = error_sites(run.get_data(), exceptions)
    summary = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "generated_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
        "test_count": result.testsRun, "test_failures": len(result.failures), "test_errors": len(result.errors),
        "test_skips": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "api_operations": len(inventory),
        "v1_operations": sum(item["path"].startswith("/api/v1/") for item in inventory),
        "generated_documentation_operations": sum(len(item["methods"]) for item in generated_documentation),
        "observed_operations": sum(bool(item["request_count"]) for item in inventory),
        "operations_with_success_status": sum(any(200 <= code < 300 for code in item["observed_statuses"]) for item in inventory),
        "operations_with_error_status": sum(any(code >= 400 for code in item["observed_statuses"]) for item in inventory),
        "explicit_http_error_sites": len(errors),
        "explicit_http_error_sites_with_observed_exception": sum(bool(item["tests"]) for item in errors),
        "explicit_http_error_sites_line_executed": sum(item["raise_line_executed"] for item in errors),
        "ci_browser_requested_operations": sum(bool(item["ci_browser_request_evidence"]) for item in inventory),
        "real_http_script_referenced_operations": sum(bool(item["real_http_script_references"]) for item in inventory),
        "no_http_evidence_or_script_reference_operations": sum(not (item["request_count"]
            or item["ci_browser_request_evidence"] or item["real_http_script_references"]) for item in inventory),
        "api_boundary_files": {},
    }
    line_coverage = json.loads((args.output / "line-branch-coverage.json").read_text())
    for filename, values in line_coverage["files"].items():
        if filename.replace("\\", "/").endswith(API_SOURCES):
            summary["api_boundary_files"][filename] = values["summary"]
    report = {"summary": summary, "operations": inventory, "explicit_http_errors": errors,
              "generated_documentation_routes": generated_documentation,
              "static_ui": {"path": "/", "methods": ["GET", "HEAD"],
                            "scope": "Packaged frontend and assets; excluded from the business API count."},
              "http_observations": requests, "exception_observations": exceptions,
              "ci_browser_evidence": browser_evidence,
              "limitations": ["Execution is not assertion coverage.",
                              "The existing unittest suite retains its mocks and dependency overrides.",
                              "Browser request evidence has no response statuses and omits context.request calls.",
                              "Static script references can miss dynamic calls and do not prove their branch ran.",
                              "Explicit HTTPException raises exclude middleware responses, framework errors and other exceptions."],
              "test_failures": [{"test": test.id(), "traceback": trace} for test, trace in result.failures],
              "test_errors": [{"test": test.id(), "traceback": trace} for test, trace in result.errors]}
    (args.output / "existing-suite-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    missing = [item["method"] + " " + item["path"] for item in inventory if not item["observed_statuses"]]
    if args.require_all_operations and missing:
        print("Missing HTTP response evidence: " + ", ".join(missing), file=sys.stderr)
        return 1
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
