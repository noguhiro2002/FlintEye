<a id="flinteye-documentation"></a>
# FlintEye ドキュメント

[English](README.md)

[プロジェクトホーム](../README.ja.md)

**開発中。** ソース、パブリックプレビューインストーラー、GHCR イメージが利用可能です。物理デバイスでの受け入れテストは現在進行中です。

- [既知の問題と検証の制限事項](KNOWN_ISSUES.ja.md)
- [貢献について](../.github/CONTRIBUTING.ja.md)
- [セキュリティ上の問題の非公開での報告](../.github/SECURITY.ja.md)

<a id="use-flinteye"></a>
## FlintEye の使用

- [Windows、macOS、または Linux へのインストール](INSTALL.ja.md)
- [OS・インストール方法別のアンインストール（データ保持・削除）](STOP_AND_UNINSTALL.ja.md)
- [カメラの追加、ライブ映像の視聴、および録画の管理](USER_GUIDE.ja.md)
- [監視インジケータ、一時停止/再開、およびデスクトップでの起動](MONITORING.ja.md)
- [Docker Compose](DOCKER.ja.md)
- [サーバーのデプロイ、HTTPS/LAN アクセス、ストレージ、および systemd](DISTRIBUTION.ja.md)

<a id="develop-and-distribute"></a>
## 開発と配布

- [ソースからの実行](MANUAL_INSTALL.ja.md)
- [パッケージのビルドとリリース / GHCR の公開](RELEASING.ja.md)
- [M1 / Apple Silicon Mac でのローカル DMG のビルドと検証](LOCAL_MACOS_BUILD.ja.md)
- [ご自身のコンピュータでの最終チェック](ACCEPTANCE.ja.md)
- [自動インストール、実際の API/GUI、アンインストールと再インストールのチェック](INSTALLATION_QA.ja.md)
- [Preview 8 の検証で見つかった問題と Preview 9 の修正](testing/PREVIEW_8_FINDINGS.ja.md)
- [安定版配布 1.2.0 前の必須実機チェック](RELEASE_CHECKLIST_1_2_0.ja.md)
- [ライセンスと許可される用途](LICENSING.ja.md)
- [環境変数のリファレンス](advanced/ENV_OPTIONS.ja.md)

<a id="advanced-reference"></a>
## 高度なリファレンス

これらのガイド内のコマンドは、ソースインストールおよびスタンドアロンツール向けです。
パッケージ版の FlintEye は、独自の MediaMTX 設定および録画保持を管理します。

- [カメラツールとトラブルシューティング](advanced/CAMERA_TOOLS.ja.md)
- [Multiview、スタンドアロン MediaMTX 録画、NTP と遅延](advanced/MEDIA_OPERATIONS.ja.md)
- [API、認証、およびログ記録](advanced/API.ja.md)
- [フロントエンド開発](advanced/DEVELOPMENT.ja.md)
