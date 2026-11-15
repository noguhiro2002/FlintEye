# 🚧 UNDER DEVELOPMENT — 開発中

**FlintEyeは現在開発中です。これは安定版リリースではなく、ソースコードで試すプレビュー版です。公開インストーラーとコンテナイメージは現在準備中です。**

[既知の問題](docs/KNOWN_ISSUES.ja.md) · [バグを報告する](https://github.com/noguhiro2002/FlintEye/issues) · [質問やアイデア](https://github.com/noguhiro2002/FlintEye/discussions)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/FlintEyeLogo-white.png">
    <source media="(prefers-color-scheme: light)" srcset="images/FlintEyeLogo.png">
    <img src="images/FlintEyeLogo-white.png" alt="FlintEye" width="520">
  </picture>
</p>
<p align="center"><strong>あなたのカメラ。あなたの録画。あなたのコンピューター。</strong><br>
USBカメラやIPカメラの監視、ライブ映像の視聴、録画の検索をブラウザで行えます。</p>
<p align="center">
  <a href="docs/RELEASING.ja.md"><img src="https://img.shields.io/badge/status-UNDER_DEVELOPMENT-orange" alt="Development preview"></a>
  <a href="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml"><img src="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml/badge.svg" alt="Checks"></a>
  <a href="docs/INSTALL.ja.md"><img src="https://img.shields.io/badge/targets-Windows_%7C_macOS_%7C_Linux-blue" alt="Platform targets"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-SUL_%2B_permission-green" alt="Sustainable Use License plus additional permission"></a>
</p>
<p align="center"><a href="README.md">English</a> · <a href="docs/README.ja.md">ドキュメント</a> · <a href="https://github.com/noguhiro2002/FlintEye/releases">ダウンロード</a></p>

![Live View、2台のカメラの Multiview、および録画再生](images/camera-workflow.gif)

*2台の実USBカメラ: **Live View → Multiview → Recordings**。現在の開発ビルドでLinux上でキャプチャしました。[MP4を視聴/ダウンロード](images/camera-workflow.mp4?raw=true)。*

<a id="quick-install"></a>
## クイックインストール

**現在利用可能:** [ソースから実行](docs/MANUAL_INSTALL.ja.md)、[ローカルのM1 Mac DMGをビルド](docs/LOCAL_MACOS_BUILD.ja.md)、または[開発用Dockerイメージをビルド](docs/DOCKER.ja.md#build-the-development-image)。

公開インストーラーはまだ利用できません。最初に計画されているダウンロードは、自動テストおよび実機テストを経た **`v1.1.2-preview.1`** です。これは「最新 (Latest)」ではなく「プレリリース (Pre-release)」としてマークされます。入手可能性については [Releases](https://github.com/noguhiro2002/FlintEye/releases) をフォローしてください。[テストチェックリスト →](docs/ACCEPTANCE.ja.md)

<details>
<summary><strong>1コマンドでのインストールを計画中 — 公開プレビューの公開後に利用可能になります</strong></summary>

これらのコマンドは計画中のプレビューの例であり、**そのリリースが公開されるまでは機能しません**。自動選択された安定バージョンではなく、固定の開発バージョンをインストールします。

**Windows — PowerShell**

```powershell
irm https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.2-preview.1/install.ps1 | iex
```

**macOS — ターミナル**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.2-preview.1/install.sh
```

**Linux — ターミナル**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.2-preview.1/install.sh
```

選択したリリースからスクリプトをダウンロードし、内容を確認してローカルで実行することもできます。パッケージ版のビルドには Python、FFmpeg、FFprobe、MediaMTX が含まれており、個別のコピーは必要ありません。Windows/macOS パッケージは署名/公証されていません。[OSの確認画面](docs/INSTALL.ja.md#unsigned-packages)を参照してください。

</details>

<details>
<summary><strong>その他のインストールオプション</strong> — バイナリパッケージ、Docker、手動インストール</summary>

- **計画中のバイナリパッケージ:** Windows EXE、macOS DMG、Linux DEB/RPM。[インストールガイド →](docs/INSTALL.ja.md)
- **Docker Compose:** 今すぐローカルでビルドできます。Linux x86-64およびARM64向けのバージョン付き公開GHCRイメージが計画されています。[Dockerガイド →](docs/DOCKER.ja.md)
- **systemd:** デスクトップログインなしで、Linuxサーバー上で常時実行します。[サーバーガイド →](docs/DISTRIBUTION.ja.md#systemd)
- **手動インストール:** 開発やカスタマイズのためにソースから実行します。[開発者向けセットアップ →](docs/MANUAL_INSTALL.ja.md)

pipアプリケーションパッケージは最初のリリースには含まれません。

</details>

<a id="quick-usage"></a>
## クイック使用方法

| Windows | macOS | Linuxデスクトップ |
| --- | --- | --- |
| スタートメニュー → **FlintEye** | アプリケーション → **FlintEye** | アプリケーション → **FlintEye** |

1. **管理者パスワードを作成します。** セットアップが自動的に開きます。ブラウザが開いたら `admin` としてサインインします。
2. **Settingsでカメラを追加します。** 英語の入門ツアーに従って、USBカメラまたはIPカメラを登録します。
3. **Live Viewを開きます。** Settingsでカメラの録画を有効にしてから、**Recordings**を開いて保存された映像を再生します。

<details>
<summary>5ステップの初回実行ガイド</summary>

![FlintEyeの5ステップの英語初回実行ガイド](images/getting-started.gif)

*UIツアー: カメラのないデモプロファイルを使用した、2026-11-15のQA修正を含む FlintEye 1.1.2 ソース。これは、インストール、実際の録画、停止、またはアンインストールではなく、5ステップのガイドを示しています。[高解像度MP4をダウンロード](images/getting-started.mp4?raw=true)。*

</details>

録画ファイルはお使いのコンピューターに保存されます。初期制限は **7日間** および **最大50GB**（または利用可能なディスク容量の半分のいずれか小さい方）です。いずれかの制限に達すると、最も古い完了した録画が削除されます。フォルダと制限は Settings で変更できます。

ブラウザを閉じても監視は継続して実行されます。停止するには、トレイメニュー/コントロールウインドウの **Stop monitoring and quit** を使用してください。

[完全なユーザーガイド →](docs/USER_GUIDE.ja.md)


<a id="documentation"></a>
## ドキュメント

FlintEyeの使用方法の詳細については、**[ドキュメント](docs/README.ja.md)**をご覧ください。

| 開始する | サーバーを運用する | ビルドと貢献 |
| --- | --- | --- |
| [インストール](docs/INSTALL.ja.md) | [Docker Compose](docs/DOCKER.ja.md) | [ソースのセットアップ](docs/MANUAL_INSTALL.ja.md) |
| [カメラと録画](docs/USER_GUIDE.ja.md) | [LANアクセスとsystemd](docs/DISTRIBUTION.ja.md) | [ビルドとリリース](docs/RELEASING.ja.md) |

<details>
<summary><strong>開発者デモ: Swagger API → WebRTC</strong></summary>

![SwaggerでカメラAPIを呼び出し、WebRTCビューを開く様子](images/api-webrtc.gif)

サインイン後に `/docs` を開き、`GET /api/v1/viewer/cameras` を試してから、同じ FlintEye サーバー上で返された `addresses.webrtc_url` を開きます。このデモでは、実際のUSBカメラと認証済みのローカルセッションを使用しています。[開発者向けMP4を視聴/ダウンロード](images/api-webrtc.mp4?raw=true)。

</details>

<a id="license"></a>
## ライセンス

FlintEyeは**ソース公開（source available）**であり、[追加許可付き持続的利用ライセンス（Sustainable Use License with additional permission）](LICENSE)の下で提供されています。個人、非営利団体、大学、公的研究機関、企業を含む営利団体は、個人的または内部的な目的で使用および変更することができます。サービスプロバイダーは、顧客所有または顧客制御のインフラストラクチャ（顧客の契約するクラウド環境を含む）において、インストール、構成、変更、運用、保守に対して料金を請求することができ、FlintEye自体には料金を請求せずに必要なコピーを提供することができます。FlintEyeまたはその変更版を販売すること、あるいは有料のホステッドサービスとして提供するには、別途ライセンスが必要です。[例とサードパーティライセンス →](docs/LICENSING.ja.md)

<a id="acknowledgements"></a>
## 謝辞

- **[FFmpeg](https://ffmpeg.org/)** — カメラのキャプチャ、動画処理、および再生変換。libx264有効版ビルドはGPLライセンスであり、リリースアセットには対応するソースとビルド手順が含まれています。
- **[MediaMTX](https://github.com/bluenviron/mediamtx)** — MITライセンスに基づくメディアトランスポートおよび録画。

サードパーティ製コンポーネントは元のライセンスを保持しており、FlintEyeの商業的制限から除外されます。[サードパーティの通知](THIRD_PARTY_NOTICES.md)を参照してください。
