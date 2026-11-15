# Contributing to FlintEye

[日本語](CONTRIBUTING.ja.md)

FlintEye is under active development. Please read the [known issues](../docs/KNOWN_ISSUES.md) and [source setup](../docs/MANUAL_INSTALL.md) before starting work. Use [Discussions](https://github.com/noguhiro2002/FlintEye/discussions) for questions and proposals, and [Issues](https://github.com/noguhiro2002/FlintEye/issues) for reproducible defects.

For a change, describe the user-visible problem, make a focused pull request, and explain how you checked it. Keep English and Japanese documentation consistent. Do not add generated frontend files, runtime configuration, recordings, credentials or local audit evidence. Preserve the license and third-party notices.

Run the applicable checks before submitting:

```sh
python -m pip install -c packaging/constraints.txt -r requirements.txt -r tests/requirements.txt
python -m unittest discover -s tests -v
python packaging/check_docs.py
npm --prefix frontend ci
npm --prefix frontend run build
(cd frontend && npx playwright install chromium && npm test)
```

Use synthetic cameras/accounts in automated tests. Native installers are built by the manual **Build release** workflow; do not claim that an automated smoke test proves physical-camera or minimum-OS compatibility. Public previews require the separate [release acceptance process](../docs/RELEASING.md).

This is source-available software under the [Sustainable Use License with additional permission](../LICENSE). A public repository does not remove its conditions. Contributions must be yours to submit and compatible with these terms; third-party components keep their own licenses.

For security problems, use [private vulnerability reporting](SECURITY.md), not a public issue.
