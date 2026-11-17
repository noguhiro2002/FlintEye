# 🚧 UNDER DEVELOPMENT — 開発中

**FlintEyeは現在開発中です。これは安定版ではなく開発プレビューです。テストには開発プレビューをご利用ください。**

現在の開発版は **1.2.0-preview.2** です。ビルドが完了すると、検証用インストーラーを [GitHub Actions](https://github.com/noguhiro2002/FlintEye/actions/workflows/build-release.yml) から取得できます。下のクイックインストールは公開済みのプレビュー版を使います。

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
<p align="center"><a href="README.md">English</a> · <a href="docs/README.ja.md">Documentation</a> · <a href="https://github.com/noguhiro2002/FlintEye/releases">Downloads</a></p>

![Live View、2台のMultiview、および録画再生](images/camera-workflow.gif)

*2台の実USBカメラ：**Live View → Multiview → Recordings**。現在の開発ビルドからLinux上でキャプチャしました。[MP4の視聴/ダウンロード](images/camera-workflow.mp4?raw=true)。*

<a id="quick-install"></a>
## クイックインストール

**開発プレビュー：[v1.1.3-preview.1](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.1.3-preview.1)。** 以下のコマンドは、そのリリースのダウンロードアセットが一覧表示された後に動作します。実機での受け入れ確認は現在進行中です。お使いのコンピュータ用のコマンドを実行し、セットアップに従ってください。Python、FFmpeg、FFprobe、MediaMTXが同梱されているため、Gitのチェックアウトやコンパイルは不要です。

**Windows — PowerShell**

```powershell
irm https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.ps1 | iex
```

**macOS — ターミナル**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.sh
```

**Linux — ターミナル**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.1.3-preview.1/install.sh
```

また、選択したリリースからスクリプトをダウンロードして内容を確認し、ローカルで実行することもできます。パッケージ版にはPython、FFmpeg、FFprobe、MediaMTXが含まれています。別途インストールする必要はありません。Windows/macOSパッケージは署名なし/公証されていません。[OS確認画面](docs/INSTALL.ja.md#unsigned-packages)をご覧ください。

<details>
<summary><strong>その他のインストールオプション</strong> — バイナリパッケージ、Docker、手動インストール</summary>

- **バイナリパッケージ:** Windows EXE、macOS DMG、Linux DEB/RPM。[インストールガイド →](docs/INSTALL.ja.md)
- **Docker Compose:** Linux x86-64およびARM64向けのバージョン管理されたGHCRイメージを使用します。[Dockerガイド →](docs/DOCKER.ja.md)
- **systemd:** デスクトップログインなしでLinuxサーバー上で常時実行します。[サーバーガイド →](docs/DISTRIBUTION.ja.md#systemd)
- **手動インストール:** 開発やカスタマイズのためにソースから実行します。[開発者向けセットアップ →](docs/MANUAL_INSTALL.ja.md)

pipアプリケーションパッケージは最初のリリースには含まれません。

</details>

### インストールしたら

| 方法 | 次の操作 |
| --- | --- |
| ワンコマンド | インストーラーの案内に従います。FlintEyeが開かなければ、下記の方法で起動します。 |
| バイナリ | Windowsはスタートメニュー、Linuxはアプリ一覧からFlintEyeを開きます。macOSはDMGからApplicationsにコピーして開きます。 |
| Docker Compose | コンテナを起動して接続先を確認します。[Dockerの初回設定](docs/DOCKER.ja.md#install-without-cloning) |
| Linuxサーバー | systemdサービスを起動し、起動時に表示される接続先を確認します。[サーバーの初回設定](docs/DISTRIBUTION.ja.md#systemd) |

起動したら[クイック使用方法](#quick-usage)に進みます。

<a id="quick-usage"></a>
## クイック使用方法

1. **FlintEyeが表示した接続先を開きます。** インストールした端末ではローカルのアドレスを使えます。このブランチをビルドした次期版では、信頼するネットワークを選ぶと、準備ができた時点でHTTPSのアドレスが表示されます。別端末では[証明書を信頼](docs/LAN_ACCESS.ja.md)してから開きます。公開版v1.1.3の初回設定はローカルから行います。
2. **管理者を作成します。** セットアップ画面かサーバーの専用ファイルから使い捨てコードを取得し、ブラウザでコードと新しいパスワードを入力します。作成後は `admin` でログインします。
3. **Settingsでカメラを追加します。** 入門ガイドに沿って、USBカメラやIPカメラを登録します。
4. **Live Viewを開きます。** 必要に応じて録画を有効にし、**Recordings**で録画した映像を再生します。

<details>
<summary>5ステップの初回実行ガイド</summary>

![FlintEyeの5ステップの英語初回実行ガイド](images/getting-started.gif)

*UIツアー：カメラのないデモプロファイルを使用した、2026-11-15のQA修正を含むFlintEye 1.1.3ソース。これはインストール、実際の録画、停止、アンインストールではなく、5ステップのガイドを示しています。[高解像度MP4をダウンロード](images/getting-started.mp4?raw=true)。*

</details>

録画データはコンピュータ上に保存されます。初期制限は **7日間** および **最大50 GB**（または利用可能なディスク容量の半分のいずれか小さい方）です。いずれかの制限に達すると、最も古い完了済みの録画が削除されます。フォルダと制限は Settings で変更できます。

ブラウザを閉じても監視は継続して実行されます。設定を開いたままカメラを一時停止するには **Stop monitoring** を使用し、完全に終了するにはデスクトップメニューの **Quit FlintEye** を使用します。[ステータスカラーと起動設定 →](docs/MONITORING.ja.md)

<details>
<summary>Linuxサーバー / SSH — パッケージインストール後</summary>

通常のサーバーユーザーとして開始します：

```sh
/opt/flinteye/FlintEye --headless
```

別のSSHセッションを使用して、起動時に表示されるデータディレクトリ内の `setup-token` を読み取ります。自身のコンピュータでトンネルを開きます：

```sh
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 your-server
```

ローカルで `http://127.0.0.1:18080` を開き、トークンを入力して管理者アカウントを作成します。そのローカルポートが使用中の場合は、左側の転送ポートとブラウザのURLを変更してください。このトンネルはHTTP管理接続を中継するものであり、WebRTC UDPビデオは転送しません。フォアグラウンドのサーバーをCtrl+Cで停止し、録画が終了するまで待機します。SSH切断後も運用するには、専用のサービスユーザーと `/var/lib/flinteye` を使用する [systemdセットアップ](docs/DISTRIBUTION.ja.md#systemd) に従ってください。手動インスタンスとサービスインスタンスを同じポートやプロファイルで実行しないでください。

</details>

<details>
<summary>1.2.0開発版：LAN上の他のPCおよびスマートフォン</summary>

次期開発バージョンのソースでは、`https://SERVER-IP:18080` にてオプトインのHTTPSが追加されており、各視聴用PC/iPhone/iPad/Androidデバイスで一度だけ証明書を信頼する必要があります。**公開版の1.1.3にはこの機能は含まれていません。** 再構築したパッケージをテストする前に、[LAN接続と信頼](docs/LAN_ACCESS.ja.md) および [1.2.0の変更点と承認ステータス](docs/DEVELOPMENT_1_2_0.ja.md) を確認してください。

</details>

[完全なユーザーガイド →](docs/USER_GUIDE.ja.md)


<a id="documentation"></a>
## ドキュメント

FlintEyeの使い方についての詳細は、**[ドキュメント](docs/README.ja.md)** をご覧ください。

| 入門ガイド | サーバーの運用 | 開発への参加 |
| --- | --- | --- |
| [インストール](docs/INSTALL.ja.md) | [Docker Compose](docs/DOCKER.ja.md) | [ソースのセットアップ](docs/MANUAL_INSTALL.ja.md) |
| [カメラと録画](docs/USER_GUIDE.ja.md) | [LANアクセスとsystemd](docs/DISTRIBUTION.ja.md) | [ビルドとリリース](docs/RELEASING.ja.md) |

<details>
<summary><strong>開発者デモ：Swagger API → WebRTC</strong></summary>

![SwaggerでカメラAPIを呼び出し、WebRTCビューを開く様子](images/api-webrtc.gif)

サインイン後に `/docs` を開き、`GET /api/v1/viewer/cameras` を試してから、同じFlintEyeサーバー上で返された `addresses.webrtc_url` を開きます。このデモでは、実際のUSBカメラと認証済みのローカルセッションを使用しています。[開発者用MP4の視聴/ダウンロード](images/api-webrtc.mp4?raw=true)。

</details>

<a id="license"></a>
## ライセンス

FlintEyeは、[追加の許可事項付き持続可能利用ライセンス](LICENSE)の下で**ソース利用可能（ソース・アベイルブル）**です。個人、非営利組織、大学、公的研究機関、企業を含む営利組織は、個人的または内部的な目的で利用および改変することができます。サービスプロバイダーは、顧客所有または顧客管理のインフラ（顧客の契約するクラウド環境を含む）上でのインストール、設定、改変、運用、保守に対して料金を請求することができ、FlintEye自体には料金を請求せずに必要なコピーを提供することができます。FlintEyeまたはその改変版を販売すること、あるいは有料のホステッドサービスとして提供することは、別途ライセンスが必要となります。[事例とサードパーティライセンス →](docs/LICENSING.ja.md)

<a id="acknowledgements"></a>
## 謝辞

- **[FFmpeg](https://ffmpeg.org/)** — カメラキャプチャ、映像処理、および再生変換。libx264を有効にしたFlintEyeの同梱ビルドはGPLライセンスです。リリースアセットには対応するソースとビルド手順が含まれています。
- **[MediaMTX](https://github.com/bluenviron/mediamtx)** — MITライセンスに基づくメディアトランスポートおよび録画。

サードパーティ製コンポーネントは元のライセンスを保持しており、FlintEyeの商業的制限からは除外されます。[サードパーティの権利表記](THIRD_PARTY_NOTICES.md)をご覧ください。
