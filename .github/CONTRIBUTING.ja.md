<a id="contributing-to-flinteye"></a>
# FlintEye への貢献

[English](CONTRIBUTING.md)

FlintEye は UNDER DEVELOPMENT です。作業を開始する前に、[既知の問題](../docs/KNOWN_ISSUES.ja.md)と[ソースのセットアップ](../docs/MANUAL_INSTALL.ja.md)をお読みください。質問や提案には [Discussions](https://github.com/noguhiro2002/FlintEye/discussions) を使用し、再現可能な不具合には [Issues](https://github.com/noguhiro2002/FlintEye/issues) を使用してください。

変更を行う際は、ユーザーから見える問題を説明し、焦点を絞ったプルリクエストを作成し、どのように確認したかを説明してください。英語と日本語のドキュメントの一貫性を保ってください。生成されたフロントエンドファイル、ランタイム設定、録画、認証情報、ローカルの監査証跡を追加しないでください。ライセンスとサードパーティの通知を保持してください。

提出前に [共通のプッシュ前検証](../docs/testing/CI_ACCEPTANCE.md#run-the-same-distribution-checks-before-pushing)を実行してください。Actions の Distribution checks と同じ項目を使います。Node.js 22、FFmpeg、FFprobe、Docker と Compose を用意し、次のコマンドを実行します。

```sh
python -m pip install -c packaging/constraints.txt -r requirements.txt -r tests/requirements.txt coverage==7.17.3
npm --prefix frontend ci
(cd frontend && npx playwright install --with-deps chromium firefox webkit)
python tools/verify_before_push.py
```

自動テストでは、合成カメラ/アカウントを使用してください。ネイティブインストーラーは **Build release** が、デフォルトブランチの対象ファイルの変更時、または手動実行時にビルドします。自動スモークテストが物理カメラまたは最小OSの互換性を証明していると主張しないでください。公開プレビューには、個別の[リリース受け入れプロセス](../docs/RELEASING.ja.md)が必要です。

これは、[追加の許可を持つ持続可能利用ライセンス](../LICENSE)に基づくソース利用可能なソフトウェアです。パブリックリポジトリであっても、その条件が免除されるわけではありません。貢献物はご自身の権利によるものであり、これらの条件と互換性がある必要があります。サードパーティ製コンポーネントはそれぞれのライセンスを維持します。

セキュリティ上の問題については、公開の Issue ではなく、[プライベートな脆弱性報告](SECURITY.ja.md)を使用してください。
