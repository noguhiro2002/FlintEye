<a id="install-flinteye"></a>
# FlintEye のインストール

[English](INSTALL.md)

[Documentation](README.ja.md)

**UNDER DEVELOPMENT.** 現在、公開リポジトリではソースコードを提供しています。公開インストーラーを準備中です。最初のリリース予定は `v1.1.2-preview.1` です。今すぐ利用するには、[source setup](MANUAL_INSTALL.ja.md)、[local M1 DMG build](LOCAL_MACOS_BUILD.ja.md)、または [development Docker](DOCKER.ja.md#build-the-development-image) を使用してください。テスト済みダウンロードについては、[Releases](https://github.com/noguhiro2002/FlintEye/releases) をフォローしてください。以下の手順では、パブリックプレビューが利用可能になった後のパッケージ版インストールについて説明しています。[acceptance checks](ACCEPTANCE.ja.md) および [known issues](KNOWN_ISSUES.ja.md) も参照してください。

<a id="choose-a-package"></a>
## パッケージの選択

| システム | パッケージ | 最小ターゲット |
| --- | --- | --- |
| Windows x64 / ARM64 | `FlintEye-VERSION-windows-ARCH-setup.exe` | Windows 10 22H2; Windows 11 |
| macOS Intel / Apple Silicon | `FlintEye-VERSION-macos-ARCH.dmg` | macOS 14 |
| Ubuntu x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.deb` | Ubuntu 24.04 |
| Rocky Linux x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.rpm` | Rocky Linux 9 / 10 |
| Raspberry Pi 4 / 5 | ARM64 DEB | 64-bit Raspberry Pi OS Bookworm 以降のテスト済みリリース |

ARCH は `amd64` または `arm64` です。これらは受入テストのターゲットであり、すべてがテスト済みであることを主張するものではありません。
32ビットシステムはサポートされていません。カメラの台数とパフォーマンスは、ハードウェアおよびストリームによって異なります。

<a id="desktop-installation"></a>
## デスクトップのインストール

- **Windows:** EXEを開き、セットアップに従って管理者パスワードを選択します。インストールはユーザーごとに行われ、スタートメニューのエントリが作成されます。
- **macOS:** DMGを開き、FlintEyeをアプリケーションフォルダにドラッグして開きます。1つのコマンドによるインストーラーは、個人の `~/Applications` フォルダを使用します。
- **Linux:** パッケージマネージャーでDEB/RPMを開き、アプリケーションメニューからFlintEyeを起動します。パッケージのインストールには管理者権限が必要です。

コマンドインストーラーはCPUを選択し、固定リリースのパッケージをダウンロードして、そのSHA-256を検証します。
コンピュータ上でソフトウェアをコンパイルすることはありません。アップグレードする前に、実行中のFlintEyeインスタンスを終了してください。
無人のLinuxサーバーの場合は、デスクトップUIを起動せずにインストールし、[systemd guide](DISTRIBUTION.ja.md#systemd)に従ってください。

<a id="included-media-tools-and-macos-recovery"></a>
## 付属のメディアツールとmacOSのリカバリ

デスクトップパッケージには、**MediaMTX、FFmpeg、FFprobe** が含まれています。HomebrewやMediaMTX個別のインストールは必要ありません。macOSアプリでは、実行ファイルは `FlintEye.app/Contents/Frameworks/bin/` にあります。以前のプライベートARM64ビルドは検査され、3つすべてが含まれていました。

以前のプライベートな 1.1.0/1.1.1 macOS インストーラー（公開ダウンロードではありません）は、保存された設定に一時的な `AppTranslocation` パスを残す場合があります。そのディレクトリが消滅した後は、MediaMTXがバンドルされているにもかかわらず起動できなくなります。UIに **Media server is unavailable** が表示され、カメラのパブリッシャーが繰り返し再起動して、USBカメラのオンとオフが切り替わる場合があります。これは、`failed to start mediamtx:direct`、`FileNotFoundError`、および古い `AppTranslocation` パスを含む `orchestrator.log` のエントリと一致します。プロセスが起動しなかったため、`mediamtx.log` が存在しない可能性もあります。

これらの既存のインストーラーの場合:

1. メニューバーアイコンを使用してFlintEyeを終了します。完全な `FlintEye.app` を `/Applications` に配置し、DMGを取り出して、インストールされたアプリを開きます。ブラウザを閉じるだけではFlintEyeは停止しません。
2. 管理者としてサインインし、**Settings → Advanced** を開きます。ランタイムJSONで、`mediamtx.direct.command` の最初のアイテムのみを `/Applications/FlintEye.app/Contents/Frameworks/bin/mediamtx` に変更します。2番目のアイテム（お使いの `mediamtx.yml` パス）およびその他のすべての設定は変更しないでください。個人のアプリケーションフォルダの場合は、`~` ではなく、完全な `/Users/YOUR_NAME/Applications/...` パスを使用してください。
3. **Replace Runtime & Restart** をクリックします。MediaMTXのステータスを確認し、ライブビュー、録画、再生を再試行します。この回避策を使用している間は、アプリをその場所に保持してください。

復旧のために `runtime.json` やデータディレクトリを削除しないでください。これらにはアカウントと設定が含まれています。別のデータディレクトリを選択していない限り、ログは `~/Library/Application Support/FlintEye/logs/` にあります。それでも起動に失敗する場合は、新しいエラーについて `orchestrator.log` と、存在する場合は `mediamtx.log` を確認してください。

ソース側の修正により、起動のたびに現在のアプリの場所からバンドルされた実行ファイルが解決され、ユーザー設定が保持されます。また、ログイン自動起動のための一時的な実行ファイルパスの保存も停止されます。既存のリリースDMGは再ビルドまたは置き換えられて**いません**。これらの自動修正には、新しいインストーラーが必要です。ネイティブmacOSおよび物理カメラのチェックは引き続き保留中です。

GitHub Actionsなしで独自のM1 Macで更新されたソースをテストするには、[local DMG build guide](LOCAL_MACOS_BUILD.ja.md)に従ってください。これには起動修復と統合された設定インターフェースが含まれており、既存のリリースダウンロードは変更されません。

<a id="unsigned-packages"></a>
## 署名のないパッケージ

初期のWindowsパッケージにはパブリッシャーの署名がありません。このリポジトリから期待されるパッケージをダウンロードしたことを確認してください。
Windowsで許可されている場合は、SmartScreenによって提示されるアプリケーションごとの確認を使用してください。

macOSパッケージは、Developer IDの公証なしで、アドホックな整合性署名を使用します。
アプリを開こうとした後、macOSから **System Settings → Privacy & Security → Open Anyway** が要求される場合があります。
Gatekeeperをグローバルに無効にしたり、インストーラースクリプトで検疫属性を削除したりしないでください。
管理対象コンピュータでは、管理者からのヘルプが必要になる場合があります。

<a id="install-a-specific-version"></a>
## 特定のバージョンのインストール

パブリックプレビューが利用可能な場合は、その正確なリリースからインストーラーまたはコマンドスクリプトを直接ダウンロードしてください。プレビューリリースは、GitHubの `releases/latest` URLでは返されません。

そのリリースから `install.sh` または `install.ps1` をダウンロードし、ローカルで実行します。
生成された各スクリプトは、自身のリリースバージョンを固定します。オプションの `--version 1.1.2-preview.1`（シェル）または `-Version 1.1.2-preview.1`（PowerShell）でその正確な開発リリースを選択します。`X.Y.Z` は、利用可能な場合に安定版リリースを選択します。タグにはプレビューサフィックスが含まれますが、インストーラーのファイル名には数値のアプリケーションバージョン（`1.1.2`）が使用されます。`--no-start` / `-NoStart` は、アプリケーションを起動せずにインストールします。

パッケージには、アプリケーションランタイムとメディアツールが含まれています。Linuxデスクトップパッケージでは、必要なデスクトップライブラリをインストールするようにシステムパッケージマネージャーにも要求されます。

<a id="update-and-remove"></a>
## アップデートと削除

完全なシャットダウン、Windowsのアンインストール動作、プログラム/データの場所、およびプロセスを実行し続ける古いインストーラーからの回復については、[Stop and uninstall FlintEye](STOP_AND_UNINSTALL.ja.md) を参照してください。

アップデートする前に監視を停止してください。設定/インベントリをバックアップし、ロールバック用に以前のインストーラーを保持してください。
置き換え用のパッケージをインストールして再起動します。ユーザーデータはインストールディレクトリの外にあります。
macOSコマンドインストーラーは、以前のアプリを `FlintEye.previous.app` として保持します。後続のアップグレードの前に、そのバックアップを脇に移動してください。

通常の削除では、録画と設定が保持されます。Windowsのアンインストーラーには、デフォルトが「データ削除なし」の個別のプロンプトが表示されます。
データを手動で削除する前に、[data locations](DISTRIBUTION.ja.md#recording-lifecycle) を参照してください。
