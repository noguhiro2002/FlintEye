# 🚧 UNDER DEVELOPMENT — 開発中

**FlintEyeは現在活発に開発中です。これは安定版リリースではなく、ソースファーストのプレビュー版です。公開インストーラーとコンテナイメージは現在準備中です。**

[既知の問題](docs/KNOWN_ISSUES.ja.md) · [バグを報告する](https://github.com/noguhiro2002/FlintEye/issues) · [質問とアイデア](https://github.com/noguhiro2002/FlintEye/discussions)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/FlintEyeLogo-white.png">
    <source media="(prefers-color-scheme: light)" srcset="images/FlintEyeLogo.png">
    <img src="images/FlintEyeLogo-white.png" alt="FlintEye" width="520">
  </picture>
</p>
<p align="center"><strong>あなたのカメラ。あなたの録画。あなたのコンピュータ。</strong><br>
USBカメラやIPカメラの監視、ライブ映像の視聴、録画の検索をブラウザで行えます。</p>
<p align="center">
  <a href="docs/RELEASING.ja.md"><img src="https://img.shields.io/badge/status-UNDER_DEVELOPMENT-orange" alt="Development preview"></a>
  <a href="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml"><img src="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml/badge.svg" alt="Checks"></a>
  <a href="docs/INSTALL.ja.md"><img src="https://img.shields.io/badge/targets-Windows_%7C_macOS_%7C_Linux-blue" alt="Platform targets"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-SUL_%2B_permission-green" alt="Sustainable Use License plus additional permission"></a>
</p>
<p align="center"><a href="README.md">English</a> · <a href="docs/README.ja.md">ドキュメント</a> · <a href="https://github.com/noguhiro2002/FlintEye/releases">ダウンロード</a></p>

<a id="quick-install"></a>
## クイックインストール

**現在利用可能:** [ソースから実行する](docs/MANUAL_INSTALL.ja.md)、[ローカルのM1 Mac DMGをビルドする](docs/LOCAL_MACOS_BUILD.ja.md)、または[開発用Dockerイメージをビルドする](docs/DOCKER.ja.md#build-the-development-image)。

公開インストーラーはまだ利用できません。最初に計画されているダウンロードは、自動テストおよび実機テストを経た **`v1.1.2-preview.1`** です。これは「最新（Latest）」ではなく「プレリリース（Pre-release）」としてマークされます。可用性については[リリース](https://github.com/noguhiro2002/FlintEye/releases)をフォローしてください。[テストチェックリスト →](docs/ACCEPTANCE.ja.md)

<details>
<summary><strong>計画されている1コマンドでのインストール — 公開プレビューの公開後に利用可能になります</strong></summary>

これらのコマンドは計画中のプレビューの例であり、**そのリリースが公開されるまでは機能しません**。これらは自動選択された安定版ではなく、固定の開発バージョンをインストールします。

**Windows — PowerShell**

```powershell
irm https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.2-preview.1/install.ps1 | iex
```

**macOS — ターミナル**

```sh
curl -fsSL https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.2-preview.1/install.sh | bash
```

**Linux — ターミナル**

```sh
curl -fsSL https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.2-preview.1/install.sh | bash
```

また、選択したリリースからスクリプトをダウンロードし、内容を確認した上でローカルで実行することもできます。パッケージ化されたビルドには、Python、FFmpeg、FFprobe、MediaMTXが含まれています。個別のコピーは必要ありません。Windows/macOSパッケージは未署名／公証されていません。[OSの確認画面](docs/INSTALL.ja.md#unsigned-packages)をご覧ください。

</details>

<details>
<summary><strong>その他のインストールオプション</strong> — バイナリパッケージ、Docker、手動インストール</summary>

- **計画中のバイナリパッケージ:** Windows EXE、macOS DMG、Linux DEB/RPM。[インストールガイド →](docs/INSTALL.ja.md)
- **Docker Compose:** 今すぐローカルでビルドできます。Linux x86-64およびARM64向けのバージョン管理された公開GHCRイメージが計画されています。[Dockerガイド →](docs/DOCKER.ja.md)
- **systemd:** デスクトップログインなしでLinuxサーバー上で常時実行します。[サーバーガイド →](docs/DISTRIBUTION.ja.md#systemd)
- **手動インストール:** 開発やカスタマイズのためにソースから実行します。[開発者向けセットアップ →](docs/MANUAL_INSTALL.ja.md)

pipアプリケーションパッケージは最初のリリースには含まれません。

</details>

<a id="quick-usage"></a>
## クイック使用方法

| Windows | macOS | Linuxデスクトップ |
| --- | --- | --- |
| スタートメニュー → **FlintEye** | アプリケーション → **FlintEye** | アプリケーション → **FlintEye** |

1. **管理者パスワードを作成します。** セットアップが自動的に開きます。ブラウザが開いたら `admin` としてサインインします。
2. **設定でカメラを追加します。** 英語の入門ツアーに従って、USBまたはIPカメラを登録します。
3. **ライブビューを開きます。** 設定でカメラの録画を有効にしてから、**録画**を開いて保存された映像を再生します。

![FlintEyeの5ステップの英語初回実行ガイド](images/getting-started.gif)

*上に5ステップの初回実行ツアーが再生されます。[最高解像度のMP4をダウンロード](images/getting-started.mp4?raw=true)。*

録画はご自身のコンピュータ内に保存されます。初期制限は **7日間** かつ **最大50 GB**（または利用可能なディスク容量の半分のいずれか小さい方）です。いずれかの制限に達すると、最も古い完了した録画から順に削除されます。フォルダと制限は設定で変更できます。

ブラウザを閉じても監視は継続します。停止するには、トレイメニュー／コントロールウィンドウの**監視を停止して終了**を使用してください。

[完全なユーザーガイド →](docs/USER_GUIDE.ja.md)

<a id="documentation"></a>
## ドキュメント

FlintEyeの使用方法の詳細については、**[ドキュメント](docs/README.ja.md)**をご覧ください。

| はじめに | サーバーの運用 | ビルドと貢献 |
| --- | --- | --- |
| [インストール](docs/INSTALL.ja.md) | [Docker Compose](docs/DOCKER.ja.md) | [ソースのセットアップ](docs/MANUAL_INSTALL.ja.md) |
| [カメラと録画](docs/USER_GUIDE.ja.md) | [LANアクセスとsystemd](docs/DISTRIBUTION.ja.md) | [ビルドとリリース](docs/RELEASING.ja.md) |

<a id="license"></a>
## ライセンス

FlintEyeは**ソース公開（source available）**であり、[追加の許可条項付き持続可能利用ライセンス（Sustainable Use License with additional permission）](LICENSE)の下で提供されています。個人、非営利組織、大学、公的研究機関、企業を含む営利組織は、個人的または内部的な目的で利用および改変することができます。サービスプロバイダーは、顧客所有または顧客管理のインフラストラクチャ（顧客が契約しているクラウド環境を含む）上で、インストール、設定、改変、運用、保守に対して料金を請求することができ、FlintEye自体に対して料金を請求することなく必要なコピーを提供することができます。FlintEyeまたはその改変版を販売すること、あるいは有料のホステッドサービスとして提供することは、別途ライセンスが必要となります。[事例とサードパーティライセンス →](docs/LICENSING.ja.md)

<a id="acknowledgements"></a>
## 謝辞

- **[FFmpeg](https://ffmpeg.org/)** — カメラキャプチャ、動画処理、および再生変換。libx264が有効な当社のビルドはGPLライセンスです。リリースアセットには対応するソースとビルド手順が含まれています。
- **[MediaMTX](https://github.com/bluenviron/mediamtx)** — メディア転送および録画（MITライセンス）。

サードパーティ製コンポーネントは元のライセンスを保持しており、FlintEyeの商業的制限の対象外です。[サードパーティの通知](THIRD_PARTY_NOTICES.md)をご覧ください。
