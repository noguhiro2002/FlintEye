<a id="flinteye-tag--status"></a>
# FlintEye @TAG@ — @STATUS@

[English](RELEASE_NOTES.md)

Application version: `@VERSION@` · Source commit: `@COMMIT@` · Build run: `@RUN_ID@`

@VALIDATION@

<a id="downloads"></a>
## Downloads

このリリースの Assets からお使いのシステムのインストーラーをダウンロードしてください:

| Computer | Installer |
| --- | --- |
| Windows x64 / ARM64 | `FlintEye-@VERSION@-windows-amd64-setup.exe` / `FlintEye-@VERSION@-windows-arm64-setup.exe` |
| macOS Intel / Apple Silicon | `FlintEye-@VERSION@-macos-amd64.dmg` / `FlintEye-@VERSION@-macos-arm64.dmg` |
| Ubuntu / Raspberry Pi OS (64-bit) | `FlintEye-@VERSION@-linux-amd64.deb` / `FlintEye-@VERSION@-linux-arm64.deb` |
| Rocky Linux | `FlintEye-@VERSION@-linux-amd64.rpm` / `FlintEye-@VERSION@-linux-arm64.rpm` |

Windows/macOS パッケージは署名なし/公証されていません。`documentation.zip` に記載されているアプリケーションごとの OS の確認手順に従ってください。アップグレードする前にモニタリングを停止してください。設定と録画は保持されます。カメラアクセス、録画、再生、トレイ/GUI の動作、および最小サポート OS については、引き続き該当する実機での受け入れ確認が必要です。

アーカイブには、英語および日本語のインストール・受け入れガイド、適用される正確な LICENSE、サードパーティの通知、および対応するソースが含まれています。`SHA256SUMS` は、それ自身を除くすべての添付ファイルをカバーしています。`build-manifest.json` には、テストされた元のバンドルが記録されています。`distribution-manifest.json` は、このリリースの選択されたファイルと GHCR イメージダイジェストを特定します。プライベートテストリリースでは、公開用のワンコマンドインストールスクリプトは省略されています。

<a id="container"></a>
## Container

`linux/amd64` または `linux/arm64` には `ghcr.io/noguhiro2002/flinteye:@IMAGE_VERSION@` を使用してください。公開イメージは匿名でのプルを許可しますが、プライベートテストには承認された GHCR ログインが必要です。プレビューイメージにはコンテナの `latest` タグがありません。添付の `compose.yaml` および `documentation.zip` の Docker ガイドを使用してください。

<a id="changes-in-this-version"></a>
## Changes in this version

この開発ビルドには、macOS での MediaMTX パス復旧、全プラットフォームでの設定の統合、非表示の Windows メディアプロセス、および終了時と Windows アンインストール時の所有 API/メディアプロセスのクリーンアップが含まれています。プレビュー対応のアップデートと、バージョンが固定されたコマンドインストーラーが含まれています。`documentation.zip` の既知の問題および受け入れガイドを参照してください。自動チェックだけでは、すべてのカメラや最小 OS が動作することは証明されません。

<a id="license"></a>
## License

個人、ならびに大学、公的研究機関、企業を含む非営利または営利組織は、個人用または内部目的で FlintEye を使用および変更できます。プロバイダーは、顧客所有または顧客管理のインフラストラクチャ（顧客が契約したクラウド環境を含む）上でのインストール、構成、変更、運用、保守に対して料金を請求することができ、FlintEye 自体の料金を請求することなく必要なコピーを提供できます。FlintEye またはその変更版の販売（バンドル内でのソフトウェア料金の徴収を含む）、あるいは有料のホステッドサービスの提供には、別途ライセンスが必要です。英語版の LICENSE が正文です。以前のバージョンのサードパーティの権利および付与は変更されません。
