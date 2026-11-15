# 🚧 UNDER DEVELOPMENT — 開発中

**FlintEyeは現在活発に開発中です。これは安定版リリースではなく、ソースコードで試すプレビュー版です。公開インストーラーとコンテナイメージは準備中です。**

[既知の問題](docs/KNOWN_ISSUES.ja.md) · [バグを報告する](https://github.com/noguhiro2002/FlintEye/issues) · [質問やアイデア](https://github.com/noguhiro2002/FlintEye/discussions)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/FlintEyeLogo-white.png">
    <source media="(prefers-color-scheme: light)" srcset="images/FlintEyeLogo.png">
    <img src="images/FlintEyeLogo-white.png" alt="FlintEye" width="520">
  </picture>
</p>
<p align="center"><strong>あなたのカメラ。あなたの録画。あなたのコンピューター。</strong><br>
USBカメラやIPカメラの監視、ライブ映像の視聴、録画のブラウザでの検索を行います。</p>
<p align="center">
  <a href="docs/RELEASING.ja.md"><img src="https://img.shields.io/badge/status-UNDER_DEVELOPMENT-orange" alt="Development preview"></a>
  <a href="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml"><img src="https://github.com/noguhiro2002/FlintEye/actions/workflows/check.yml/badge.svg" alt="Checks"></a>
  <a href="docs/INSTALL.ja.md"><img src="https://img.shields.io/badge/targets-Windows_%7C_macOS_%7C_Linux-blue" alt="Platform targets"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-SUL_%2B_permission-green" alt="Sustainable Use License plus additional permission"></a>
</p>
<p align="center"><a href="README.md">English</a> · <a href="docs/README.ja.md">ドキュメント</a> · <a href="https://github.com/noguhiro2002/FlintEye/releases">ダウンロード</a></p>

![Live View、2台のカメラのMultiview、および録画再生](images/camera-workflow.gif)

*2台の実物のUSBカメラ: **Live View → Multiview → Recordings**。現在の開発ビルドでLinux上でキャプチャしました。[MP4の視聴/ダウンロード](images/camera-workflow.mp4?raw=true)。*

<a id="quick-install"></a>
## クイックインストール

**現在利用可能:** [ソースから実行](docs/MANUAL_INSTALL.ja.md)、[ローカルのM1 Mac用DMGを作成](docs/LOCAL_MACOS_BUILD.ja.md)、または[開発用Dockerイメージをビルド](docs/DOCKER.ja.md#build-the-development-image)。

公開インストーラーはまだ利用できません。最初に計画されているダウンロードは、自動テストおよび実機でのチェックを経た **`v1.1.3-preview.1`** です。これは「最新版（Latest）」ではなく「プレリリース（Pre-release）」としてマークされます。入手方法については [Releases](https://github.com/noguhiro2002/FlintEye/releases) をフォローしてください。[テストチェックリスト →](docs/ACCEPTANCE.ja.md)

<details>
<summary><strong>1コマンドでのインストールの計画 — 公開プレビューの公開後に利用可能になります</strong></summary>

これらのコマンドは計画中のプレビューの例であり、**そのリリースが公開されるまでは機能しません**。自動選択された安定版ではなく、固定の開発バージョンをインストールします。

**Windows — PowerShell**

```powershell
irm https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.ps1 | iex
```

**macOS — Terminal**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.sh
```

**Linux — Terminal**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.sh
```

選択したリリースからスクリプトをダウンロードして確認し、ローカルで実行することもできます。パッケージ化されたビルドには、Python、FFmpeg、FFprobe、MediaMTXが含まれています。個別のコピーは必要ありません。Windows/macOSパッケージは署名なし／公証されていません。詳細は[OSの確認画面](docs/INSTALL.ja.md#unsigned-packages)をご覧ください。

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
2. **Settingsでカメラを追加します。** 英語の開始ガイドに従って、USBカメラまたはIPカメラを登録します。
3. **Live Viewを開きます。** Settingsでカメラの録画を有効にし、**Recordings** を開いて保存された映像を再生します。

<details>
<summary>5ステップの初回実行ガイド</summary>

![FlintEyeの5ステップの英語の初回実行ガイド](images/getting-started.gif)

*UIツアー: カメラのないデモプロファイルを使用した、2026-11-15のQA修正を含むFlintEye 1.1.3ソース。これは、インストール、実際の録画、停止、またはアンインストールではなく、5ステップのガイドを示しています。[高解像度MP4のダウンロード](images/getting-started.mp4?raw=true)。*

</details>

Recordings はお使いのコンピューターに保存されます。初期制限は **7日間** かつ **最大50 GB**（または利用可能なディスク容量の半分少ない方）です。いずれかの制限に達すると、最も古い完了した録画が削除されます。フォルダと制限は Settings で変更してください。

ブラウザを閉じても監視は継続して実行されます。設定を開いたままカメラを一時停止するには **Stop monitoring** を使用するか、完全に終了するにはデスクトップメニューの **Quit FlintEye** を使用します。[ステータスカラーと起動時の設定 →](docs/MONITORING.ja.md)

[完全なユーザーガイド →](docs/USER_GUIDE.ja.md)


<a id="documentation"></a>
## ドキュメント

FlintEyeの使用方法の詳細については、**[ドキュメント](docs/README.ja.md)** をご覧ください。

| スタートガイド | サーバーの運用 | ビルドと貢献 |
| --- | --- | --- |
| [インストール](docs/INSTALL.ja.md) | [Docker Compose](docs/DOCKER.ja.md) | [ソースのセットアップ](docs/MANUAL_INSTALL.ja.md) |
| [カメラと録画](docs/USER_GUIDE.ja.md) | [LANアクセスとsystemd](docs/DISTRIBUTION.ja.md) | [ビルドとリリース](docs/RELEASING.ja.md) |

<details>
<summary><strong>開発者デモ: Swagger API → WebRTC</strong></summary>

![SwaggerでカメラAPIを呼び出し、そのWebRTCビューを開く様子](images/api-webrtc.gif)

サインイン後に `/docs` を開き、`GET /api/v1/viewer/cameras` を試してから、同じFlintEyeサーバー上で返された `addresses.webrtc_url` を開きます。このデモでは、実物のUSBカメラと認証済みのローカルセッションを使用しています。[開発者向けMP4の視聴/ダウンロード](images/api-webrtc.mp4?raw=true)。

</details>

<a id="license"></a>
## ライセンス

FlintEyeはソース公開型（**source available**）であり、[追加の許可事項付き持続可能利用ライセンス（Sustainable Use License with additional permission）](LICENSE)の下で提供されています。個人、非営利団体、営利企業（大学、公的研究機関、企業を含む）は、個人的または内部的な目的で利用および改変することができます。サービスプロバイダーは、顧客が所有または制御するインフラ（顧客が契約したクラウド環境を含む）上で、インストール、設定、改変、運用、保守に対する料金を請求することや、FlintEye自体の料金を請求することなく必要なコピーを提供することができます。FlintEyeまたはその改変版を販売すること、あるいは有料のホステッドサービスとして提供するには、別途ライセンスが必要です。[例とサードパーティライセンス →](docs/LICENSING.ja.md)

<a id="acknowledgements"></a>
## 謝辞

- **[FFmpeg](https://ffmpeg.org/)** — カメラキャプチャ、映像処理、および再生変換。libx264が有効な当社のビルドはGPLライセンスの下で提供されており、リリースアセットには対応するソースとビルド手順が含まれています。
- **[MediaMTX](https://github.com/bluenviron/mediamtx)** — メディア転送および録画（MITライセンス）。

サードパーティ製コンポーネントは元のライセンスを保持しており、FlintEyeの商業的制限の対象外です。[サードパーティの権利表記](THIRD_PARTY_NOTICES.md)をご覧ください。
