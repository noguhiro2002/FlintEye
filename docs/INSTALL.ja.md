<a id="install-flinteye"></a>
# FlintEye のインストール

[English](INSTALL.md)

[Documentation](README.ja.md)

**UNDER DEVELOPMENT.** 現在、公開リポジトリではソースコードを提供しています。公開インストーラーを準備中です。最初のリリース予定は `v1.1.2-preview.1` です。今すぐ利用するには、[source setup](MANUAL_INSTALL.ja.md)、[local M1 DMG build](LOCAL_MACOS_BUILD.ja.md)、または[development Docker](DOCKER.ja.md#build-the-development-image)を使用してください。テスト済みのダウンロードについては、[Releases](https://github.com/noguhiro2002/FlintEye/releases)に従ってください。以下の手順では、パブリックプレビューが利用可能になった後のパッケージ版のインストールについて説明しています。[acceptance checks](ACCEPTANCE.ja.md)および[known issues](KNOWN_ISSUES.ja.md)を参照してください。

<a id="choose-a-package"></a>
## パッケージの選択

| システム | パッケージ | 最小ターゲット |
| --- | --- | --- |
| Windows x64 / ARM64 | `FlintEye-VERSION-windows-ARCH-setup.exe` | Windows 10 22H2; Windows 11 |
| macOS Intel / Apple Silicon | `FlintEye-VERSION-macos-ARCH.dmg` | macOS 14 |
| Ubuntu x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.deb` | Ubuntu 24.04 |
| Rocky Linux x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.rpm` | Rocky Linux 9 / 10 |
| Raspberry Pi 4 / 5 | ARM64 DEB | 64-bit Raspberry Pi OS Bookworm 以降のテスト済みリリース |

ARCH は `amd64` または `arm64` です。これらは動作確認のターゲットであり、すべてがテスト済みであることを主張するものではありません。
32ビットシステムはサポートされていません。カメラの台数とパフォーマンスは、ハードウェアとストリームに依存します。

<a id="desktop-installation"></a>
## デスクトップのインストール

- **Windows:** EXE を開き、セットアップに従って管理者パスワードを選択します。インストールはユーザーごとに行われ、[スタート] メニューのエントリが作成されます。
- **macOS:** DMG を開き、FlintEye を [アプリケーション] にドラッグして開きます。1行コマンドインストーラーは、個人の `~/Applications` フォルダを使用します。
- **Linux:** パッケージマネージャーで DEB/RPM を開き、アプリケーションメニューから FlintEye を起動します。パッケージのインストールには管理者権限が必要です。

コマンドインストーラーは CPU を選択し、固定リリースのパッケージをダウンロードして、その SHA-256 を検証します。
コンピューター上でソフトウェアのコンパイルは行いません。アップグレードする前に、実行中の FlintEye インスタンスを終了してください。
無人の Linux サーバーの場合は、デスクトップ UI を起動せずにインストールし、[systemd guide](DISTRIBUTION.ja.md#systemd)に従ってください。

<a id="included-media-tools-and-macos-recovery"></a>
## 付属のメディアツールと macOS の復旧

デスクトップパッケージには、**MediaMTX、FFmpeg、FFprobe** が含まれています。別途 Homebrew や MediaMTX をインストールする必要はありません。macOS アプリでは、実行ファイルは `FlintEye.app/Contents/Frameworks/bin/` にあります。以前のプライベート ARM64 ビルドは検査され、3つすべてが含まれていました。

以前のプライベートな 1.1.0 / 1.1.1 macOS インストーラー（公開ダウンロードではありません）では、保存された設定に一時的な `AppTranslocation` パスが残る場合があります。そのディレクトリが消滅すると、MediaMTX はバンドルされているにもかかわらず起動できなくなります。UI に **Media server is unavailable** と表示され、カメラパブリッシャーが繰り返し再起動して、USB カメラのオンとオフが切り替わる場合があります。これは、`failed to start mediamtx:direct`、`FileNotFoundError`、および古い `AppTranslocation` のパスを含む `orchestrator.log` エントリと一致します。プロセスが一度も起動しなかったため、`mediamtx.log` が存在しない可能性があります。

これらの既存のインストーラーの場合：

1. メニューバーのアイコンを使用して FlintEye を終了します。完全な `FlintEye.app` を `/Applications` に配置し、DMG を取り出し、インストールされたアプリを開きます。ブラウザを閉じただけでは FlintEye は停止しません。
2. 管理者としてサインインし、**Settings → Advanced** を開きます。ランタイム JSON で、`mediamtx.direct.command` の最初のアイテムのみを `/Applications/FlintEye.app/Contents/Frameworks/bin/mediamtx` に変更します。2番目のアイテム（ご自身の `mediamtx.yml` パス）およびその他のすべての設定は変更しないでください。個人の Applications フォルダの場合は、`~` ではなく完全な `/Users/YOUR_NAME/Applications/...` パスを使用してください。
3. **Replace Runtime & Restart** をクリックします。MediaMTX のステータスを確認し、ライブビュー、録画、再生を再試行します。この回避策を使用している間は、アプリをその場所に維持してください。

復旧のために `runtime.json` またはデータディレクトリを削除しないでください。アカウントと設定が含まれています。別のデータディレクトリを選択していない限り、ログは `~/Library/Application Support/FlintEye/logs/` にあります。それでも起動に失敗する場合は、`orchestrator.log` および（存在する場合は）新しいエラーについて `mediamtx.log` を確認してください。

ソースの修正により、起動ごとに現在のアプリの場所からバンドルされた実行ファイルが解決され、ユーザー設定が保持されるようになります。また、ログイン時の自動起動用の一時的な実行ファイルパスの保存も停止されます。既存のリリース DMG は再ビルドまたは置き換えられていません。それらの自動修正には新しいインストーラーが必要です。ネイティブ macOS および物理カメラのチェックは保留中です。

GitHub Actions なしでご自身の M1 Mac で更新されたソースをテストするには、[local DMG build guide](LOCAL_MACOS_BUILD.ja.md)に従ってください。起動の修復と統合された設定インターフェイスが含まれており、既存のリリースダウンロードは変更されません。

<a id="unsigned-packages"></a>
## 署名なしパッケージ

初期の Windows パッケージにはパブリッシャーの署名がありません。このリポジトリから期待されるパッケージをダウンロードしたことを確認してください。
Windows が許可する場合は、SmartScreenによって表示されるアプリケーションごとの確認を使用してください。

macOS プレビューパッケージは、Developer ID による公証なしのアドホック整合性署名を使用しています。ビルドは、古いライセンスバンドルに誤ってコピーされたテスト/デバッグバイナリを含め、無効なバンドル署名を拒否するようになりました。有効なアドホック署名であっても信頼できるパブリッシャーが確立されるわけではないため、クリーンなマシンの場合、Gatekeeper の拒否が想定されます。ダウンロードしたアプリの最初の起動は、引き続き明示的な受け入れチェックです。[Apple's explanation of app checks](https://support.apple.com/102445)および[signature verification](https://developer.apple.com/library/archive/technotes/tn2206/)を参照してください。
アプリを開こうとした後、macOS で **System Settings → Privacy & Security → Open Anyway** が必要になる場合があります。
インストーラー スクリプトで Gatekeeper をグローバルに無効にしたり、検疫属性を削除したりしないでください。
管理対象コンピューターでは、管理者の助けが必要になる場合があります。

<a id="install-a-specific-version"></a>
## 特定のバージョンのインストール

パブリックプレビューが利用可能な場合は、その正確なリリースからインストーラーまたはコマンドスクリプトを直接ダウンロードしてください。プレビューリリースは GitHub の `releases/latest` URL では返されません。

そのリリースから `install.sh` または `install.ps1` をダウンロードし、ローカルで実行します。
生成された各スクリプトは、自身のリリースバージョンを固定します。オプションの `--version 1.1.2-preview.1`（シェル）または `-Version 1.1.2-preview.1`（PowerShell）によってその正確な開発リリースが選択され、`X.Y.Z` によって利用可能な場合は安定版リリースが選択されます。タグにはプレビュースフィックスが含まれ、インストーラーのファイル名には数値のアプリケーションバージョン（`1.1.2`）が使用されます。`--no-start` / `-NoStart` は、アプリケーションを起動せずにインストールします。

パッケージには、アプリケーションランタイムとメディアツールが含まれています。Linux デスクトップパッケージでは、システムパッケージマネージャーに対して、必要なデスクトップライブラリのインストールも要求されます。

<a id="update-and-remove"></a>
## 更新と削除

完全にシャットダウンする方法、Windows のアンインストール動作、プログラム/データの場所、およびプロセスを実行したままにする古いインストーラーからの復旧については、[Stop and uninstall FlintEye](STOP_AND_UNINSTALL.ja.md)を参照してください。

更新する前に監視を停止してください。構成/インベントリをバックアップし、ロールバック用に前のインストーラーを保持してください。
置換パッケージをインストールして再起動します。ユーザーデータはインストールディレクトリの外にあります。
macOS コマンドインストーラーは前のアプリを `FlintEye.previous.app` として保持します。後続のアップグレードの前に、そのバックアップを脇に移動してください。

通常の削除では、録画と設定が保持されます。Windows のアンインストーラーには、個別のデフォルトで [データ削除なし (No)] のプロンプトが表示されます。
手動でデータを削除する前に、[data locations](DISTRIBUTION.ja.md#recording-lifecycle)を参照してください。
