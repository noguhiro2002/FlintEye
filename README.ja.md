# 🚧 UNDER DEVELOPMENT — 開発中

**FlintEyeは現在開発中です。これは安定版ではなく開発プレビューです。テストには開発プレビューをご利用ください。**

現在の開発プレビュー版は **1.2.0-preview.7** です。以下のクイックインストールコマンドで導入できます。macOSでは初回起動時の承認手順に従ってください。自動テストの結果と実機での確認項目は[開発プレビュー版の検証一覧](docs/RELEASE_CHECKLIST_1_2_0.ja.md)で確認できます。

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

[管理者権限なしでインストールする方法](#install-without-administrator-privileges)

**開発プレビュー：[v1.2.0-preview.7](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.2.0-preview.7)。** 実機での受け入れ確認は現在進行中です。お使いのコンピュータ用のコマンドを実行し、セットアップに従ってください。Python、FFmpeg、FFprobe、MediaMTXが同梱されているため、Gitのチェックアウトやコンパイルは不要です。

**Windows — PowerShell**

```powershell
irm https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.7/install.ps1 | iex
```

**macOS — ターミナル**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.7/install.sh
```

**Linux — ターミナル**

```sh
bash -c 'set -e; script=$(mktemp); cleanup() { rm -f -- "$script"; }; trap cleanup EXIT; curl -fsSL "$1" -o "$script"; bash "$script"' -- https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.7/install.sh
```

また、選択したリリースからスクリプトをダウンロードして内容を確認し、ローカルで実行することもできます。パッケージ版にはPython、FFmpeg、FFprobe、MediaMTXが含まれています。別途インストールする必要はありません。Windows/macOSパッケージは署名なし/公証されていません。[OS確認画面](docs/INSTALL.ja.md#unsigned-packages)をご覧ください。

<a id="macos-trust"></a>
**macOSでの初回起動:** このコミュニティプレビューを開こうとした後、要求があれば **システム設定 → プライバシーとセキュリティ → このまま開く → 開く** を使用してください。このアプリはアドホック署名されており、公証されていません。インストールしただけでは実行権限が付与されません。[macOSでファイルが見つからないと言われた場合 →](docs/INSTALL.ja.md#unsigned-packages)

<a id="install-without-administrator-privileges"></a>
### 管理者権限なしでインストール

- **Windows** — 一般ユーザーでEXEまたはPowerShellのインストーラーを実行します。インストール先は `%LOCALAPPDATA%\Programs\FlintEye` です。スタートメニューから起動できます。削除するときはFlintEyeを終了し、**設定 → アプリ → FlintEye → アンインストール**を選びます。データを保持する既定の選択を使ってください。
- **macOS** — 一般ユーザーでワンコマンド版を実行するか、DMG内の `FlintEye.app` を個人用の `~/Applications` にコピーして開きます。必要に応じて[初回起動の承認手順](#macos-trust)に従ってください。削除するときはメニューバーで **Disable start at login and quit** を選び、そのアプリをゴミ箱に移動します。組織管理のMacでは、起動に管理者の承認が必要な場合があります。
- **Linux** — スクリプトをダウンロードし、次のコマンドを実行します。同じビルドのActions成果物で試す場合は、ZIPを展開し、そのフォルダで `--package-directory .` を付けて実行します。[install.shをダウンロード](https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.7/install.sh)

```sh
bash ./install.sh --user
```

対応するUbuntu、Debian、64ビット版Raspberry Pi OSでは `dpkg-deb`、Rocky Linux、AlmaLinux、RHELでは `rpm2cpio` と `cpio` を使います。[実行に必要なライブラリ](packaging/nfpm.yaml)はOS側に入っている必要があります。インストール先は `~/.local/opt/flinteye-user` です。`"$HOME/.local/opt/flinteye-user/FlintEye"` で起動し、案内されたアドレスを開きます。サーバーでは `--headless` を付けて起動し、Ctrl+Cで終了します。

削除するときはFlintEyeを終了し、同じスクリプトで `bash ./install.sh --user --uninstall` を実行します。設定と録画はプログラムフォルダの外に保存してください。既定のデータ保存先は `$XDG_DATA_HOME/flinteye` で、`XDG_DATA_HOME` が未設定なら `~/.local/share/flinteye` です。カスタムプロファイルでは、削除する前にそのプロファイルのログイン時起動を無効にしてください。

同じ端末で使う場合は **This computer only** を選びます。USBカメラやマイクにはOSの利用許可が必要です。別端末から接続する場合、ファイアウォールや証明書の設定に管理者の対応が必要なことがあります。[LAN・VPN接続ガイド](docs/LAN_ACCESS.ja.md)

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
| Linux `--user` | `"$HOME/.local/opt/flinteye-user/FlintEye"` を実行し、案内された接続先を開きます。 |
| バイナリ | Windowsはスタートメニュー、Linuxはアプリ一覧からFlintEyeを開きます。macOSはDMGからApplicationsにコピーして開きます。 |
| Docker Compose | コンテナを起動して接続先を確認します。[Dockerの初回設定](docs/DOCKER.ja.md#install-without-cloning) |
| Linuxサーバー | systemdサービスを起動し、起動時に表示される接続先を確認します。[サーバーの初回設定](docs/DISTRIBUTION.ja.md#systemd) |

起動したら[クイック使用方法](#quick-usage)に進みます。アンインストールについては[こちら](#uninstall)をご覧ください。

<a id="quick-usage"></a>
## クイック使用方法

1. **FlintEyeが表示した接続先を開きます。** インストールした端末ではローカルのアドレスを使えます。初回起動時に信頼するネットワークを選んでください。FlintEyeは準備ができた時点でHTTPSのアドレスを表示します。別端末では[証明書を信頼](docs/LAN_ACCESS.ja.md)してから開きます。
2. **管理者を作成します。** デスクトップ版では、FlintEyeが開いたブラウザでパスワードを設定します。閉じた場合はアプリのメニューから **Open FlintEye** を選ぶと再開できます。Dockerやヘッドレスサーバーでは、サーバーの `setup-token` ファイルにある使い捨てコードを入力します。作成後は `admin` でログインします。
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

この開発プレビューには `https://SERVER-IP:18080` にてオプトインのHTTPSが追加されており、各視聴用PC/iPhone/iPad/Androidデバイスで一度だけ証明書を信頼する必要があります。プレビューパッケージをテストする際は、[LAN接続と信頼](docs/LAN_ACCESS.ja.md) および [1.2.0の変更点と承認ステータス](docs/DEVELOPMENT_1_2_0.ja.md) を確認してください。

</details>

[完全なユーザーガイド →](docs/USER_GUIDE.ja.md)

<a id="uninstall"></a>
## アンインストール

**アカウント、設定、録画はデフォルトで保持されます。** 削除する前に FlintEye を完全に終了してください。ブラウザを閉じたり **Stop monitoring** を選択してもアプリケーションは実行されたままになります。

| インストール方法 | アプリケーションの削除 |
| --- | --- |
| Windows スクリプト / EXE / Actions パッケージ | Windows 11: **設定 → アプリ → インストールされているアプリ**。Windows 10: **設定 → アプリ → アプリと機能**。**FlintEye → アンインストール**を選択し、データ保持の選択はデフォルトのままにします。 |
| macOS スクリプト | メニューバーアイコン → **Disable start at login and quit** を選択し、`~/Applications/FlintEye.app` をゴミ箱に移動します（またはカスタムインストールフォルダを使用）。ロールバック用のコピーが不要な場合は `FlintEye.previous.app` も削除してください。 |
| macOS DMG / ローカルビルド DMG | **Disable start at login and quit** を選択し、`/Applications/FlintEye.app` をゴミ箱に移動します（または選択したフォルダから削除）。 |
| Linux `--user` | ダウンロードしたスクリプトで `bash ./install.sh --user --uninstall` を実行します。 |
| Linux スクリプト / DEB | ログイン起動を無効にして終了し、`sudo apt-get remove flinteye` を実行します。 |
| Linux スクリプト / RPM | ログイン起動を無効にして終了し、`sudo dnf remove flinteye` を実行します。 |
| Docker Engine, ダウンロードした `compose.yaml` | 元のデプロイメントフォルダで `docker compose down` を実行します。 |
| Docker Desktop, ダウンロードした `compose.desktop.yaml` | 元のデプロイメントフォルダで `docker compose -f compose.desktop.yaml down` を実行します。ソースチェックアウトの場合は `-f deploy/compose.desktop.yaml` を使用してください。 |
| 開発用 Docker | チェックアウトのルートから `docker compose -f deploy/compose.dev.yaml down` を実行します。 |
| systemd | `sudo systemctl disable --now flinteye` を実行し、[手動インストールしたサービスとアプリケーションを削除](docs/STOP_AND_UNINSTALL.ja.md#systemd)します。 |
| 手動ソース / 仮想環境 | ログイン起動を無効にし、ランチャー/ターミナルプロセスやサービスを停止してから、データを保持した上で専用のチェックアウトおよび仮想環境を削除します。[ソースの削除 →](docs/STOP_AND_UNINSTALL.ja.md#manual-source-and-virtual-environment) |

ネイティブアプリの削除では、同梱されているPython/FastAPI、FFmpeg、FFprobe、MediaMTXも削除されます。Dockerは `down` 後もデータボリュームとキャッシュされたイメージを保持します。[Dockerの削除](docs/STOP_AND_UNINSTALL.ja.md#docker-compose)を参照してください。データの消去は、別途明確な選択が必要です。

[完全な削除ガイド：データの保存場所、オプションのデータ消去、起動設定の復旧、LAN証明書の削除 →](docs/STOP_AND_UNINSTALL.ja.md)

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
