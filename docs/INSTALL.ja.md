<a id="install-flinteye"></a>
# FlintEye のインストール

[English](INSTALL.md)

[Documentation](README.ja.md)

**UNDER DEVELOPMENT.** To test the current fixes, use the **1.2.0-preview.3 Actions packages and local installer scripts** in [Quick Install](../README.md#quick-install). The public [1.1.3-preview.1 scripts](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.1.3-preview.1) install the old version; the native password window, old icon and internal RTSP display there are not evidence that the new build was installed. Check **Information → System** for the exact preview and source commit. Real-device acceptance is still in progress. [Source setup](MANUAL_INSTALL.ja.md), [local M1 DMG builds](LOCAL_MACOS_BUILD.ja.md) and [development Docker](DOCKER.ja.md#build-the-development-image) remain available. See [acceptance checks](ACCEPTANCE.ja.md) and [known issues](KNOWN_ISSUES.ja.md).

<a id="choose-a-package"></a>
## パッケージの選択

| システム | パッケージ | 最小ターゲット |
| --- | --- | --- |
| Windows x64 / ARM64 | `FlintEye-VERSION-windows-ARCH-setup.exe` | Windows 10 22H2; Windows 11 |
| macOS Intel / Apple Silicon | `FlintEye-VERSION-macos-ARCH.dmg` | macOS 14 |
| Ubuntu x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.deb` | Ubuntu 24.04 |
| Rocky Linux x64 / ARM64 | `FlintEye-VERSION-linux-ARCH.rpm` | Rocky Linux 9 / 10 |
| Raspberry Pi 4 / 5 | ARM64 DEB | 64-bit Raspberry Pi OS Bookworm またはそれ以降のテスト済みリリース |

ARCH は `amd64` または `arm64` です。これらは受け入れターゲットであり、すべてがテスト済みであることを主張するものではありません。
32 ビットシステムはサポートされていません。カメラの台数とパフォーマンスはハードウェアとストリームに依存します。

<a id="desktop-installation"></a>
## デスクトップへのインストール

- **Windows:** EXEを開き、セットアップに従います。現在のビルドでは、管理者パスワードの入力にブラウザが開きます。インストールはユーザーごとに行われ、スタートメニューのエントリが作成されます。
- **macOS:** DMGを開き、FlintEyeをアプリケーションフォルダにドラッグして開きます。ワンコマンドインストーラーは、個人の `~/Applications` フォルダを使用します。
- **Linux:** パッケージマネージャーで DEB/RPM を開き、アプリケーションメニューから FlintEye を起動します。パッケージのインストールには管理者権限が必要です。

コマンドインストーラーは CPU を選択し、固定された1つのリリースのパッケージをダウンロードして、その SHA-256 を検証します。
コンピューター上でソフトウェアをコンパイルすることはありません。アップグレードする前に、実行中の FlintEye インスタンスを終了してください。
無人 Linux サーバーの場合は、デスクトップ UI を起動せずにインストールし、[systemd ガイド](DISTRIBUTION.ja.md#systemd)に従ってください。

<a id="included-media-tools-and-macos-recovery"></a>
## 付属のメディアツールと macOS のリカバリ

<a id="screen-recording-requests-in-older-previews"></a>
### Screen Recording requests in older previews

FlintEye does not record your desktop. Older camera discovery included FFmpeg's `Capture screen` inputs and opened them while querying camera modes, causing repeated **Screen Recording** permission dialogs. In **1.2.0-preview.3**, screen inputs are excluded before probing. Saved camera indices are checked before capture too, so a removed camera cannot make its old index select the screen. OBS virtual cameras remain supported as camera inputs. You do not need to grant Screen Recording permission to FlintEye; microphone access is separate and is used only when camera audio is enabled. Confirm absence of repeated prompts on your Mac as part of physical-device QA.

デスクトップパッケージには **MediaMTX、FFmpeg、FFprobe** が含まれています。個別の Homebrew や MediaMTX のインストールは不要です。macOS アプリでは、実行ファイルは `FlintEye.app/Contents/Frameworks/bin/` にあります。以前のプライベート ARM64 ビルドは検査され、3つすべてが含まれていました。

以前のプライベートな 1.1.0/1.1.1 macOS インストーラー（パブリックダウンロードではありません）は、保存された設定に一時的な `AppTranslocation` パスを保持する場合があります。そのディレクトリが消滅すると、MediaMTX はバンドルされているにもかかわらず起動できなくなります。UI に **Media server is unavailable** が表示され、カメラパブリッシャーが繰り返し再起動して、USB カメラのオンとオフが切り替わる場合があります。これは、`failed to start mediamtx:direct`、`FileNotFoundError`、および古い `AppTranslocation` パスを含む `orchestrator.log` エントリと一致します。プロセスが一度も起動しなかったため、`mediamtx.log` が存在しない可能性もあります。

これらの既存のインストーラーの場合:

1. メニューバーアイコンから **Quit FlintEye** を選択します。完全な `FlintEye.app` を `/Applications` に配置し、DMGを取り出し、インストールされたアプリを開きます。ブラウザを閉じただけでは FlintEye は停止しません。
2. 管理者としてサインインし、**Settings → Advanced** を開きます。ランタイム JSON で、`mediamtx.direct.command` の最初のアイテムのみを `/Applications/FlintEye.app/Contents/Frameworks/bin/mediamtx` に変更します。2番目のアイテム（お客様の `mediamtx.yml` パス）およびその他の設定はすべて変更しないでください。個人の Applications フォルダの場合は、`~` ではなく、フルパスの `/Users/YOUR_NAME/Applications/...` を使用してください。
3. **Replace Runtime & Restart** をクリックします。MediaMTX のステータスを確認し、Live View、録画、および再生を再試行します。このワークアラウンドを使用している間は、アプリをその場所に維持してください。

復旧のために `runtime.json` やデータディレクトリを削除しないでください。これらにはアカウントと設定が含まれています。別のデータディレクトリを選択していない場合、ログは `~/Library/Application Support/FlintEye/logs/` の下にあります。それでも起動に失敗する場合は、`orchestrator.log` および（存在する場合は）新しいエラーに関する `mediamtx.log` を確認してください。

ソースの修正により、起動するたびに現在のアプリの場所からバンドルされた実行ファイルが解決され、ユーザー設定が保持されるようになります。また、ログイン自動起動のための一時的な実行ファイルパスの保存も停止されます。これらの修正は 1.1.3 プレビューインストーラーに含まれています。ネイティブの自動パッケージチェックは合格しましたが、実際のカメラ接続と、ダウンロードしたアプリの初回起動時のOS確認は、引き続き実機での検証が必要です。古いプライベートインストーラーファイルは変更されません。

GitHub Actions を使用せずに独自の M1 Mac で更新されたソースをテストするには、[ローカル DMG ビルドガイド](LOCAL_MACOS_BUILD.ja.md)に従ってください。これには起動修復と統合された Settings インターフェイスが含まれており、既存のリリースダウンロードは変更されません。

<a id="unsigned-packages"></a>
## 未署名のパッケージ

初期の Windows パッケージにはパブリッシャー署名がありません。このリポジトリから想定通りのパッケージをダウンロードしたことを確認してください。
Windows で許可されている場合は、SmartScreenによって表示されるアプリケーションごとの確認を使用してください。

macOS プレビューパッケージは、Developer ID による公証なしのアドホック整合性署名を使用しています。現在のビルドでは、古いライセンスバンドルに誤ってコピーされたテスト/デバッグ用バイナリを含め、無効なバンドル署名が拒否されます。有効なアドホック署名であっても、信頼できるパブリッシャーが確立されるわけではなく、クリーンなマシンでは Gatekeeper による拒否が予想されます。ダウンロードしたアプリの初回起動は、引き続き明示的な受け入れチェックとなります。[アプリチェックに関する Apple の説明](https://support.apple.com/102445)および[署名検証](https://developer.apple.com/library/archive/technotes/tn2206/)を参照してください。
アプリを開こうとした後、macOS で **システム設定 → プライバシーとセキュリティ → このまま開く** が要求される場合があります。
Gatekeeper をグローバルに無効にしたり、インストーラースクリプトで隔離属性を削除したりしないでください。
管理対象コンピューターでは、管理者の支援が必要になる場合があります。

<a id="install-a-specific-version"></a>
## 特定のバージョンのインストール

正確なプレビューリリースからインストーラーまたはコマンドスクリプトを directly ダウンロードします。プレビューリリースは GitHub の `releases/latest` URL では返されません。

そのリリースから `install.sh` または `install.ps1` をダウンロードして、ローカルで実行します。
生成される各スクリプトは、自身のリリースバージョンを固定します。オプションの `--version 1.1.3-preview.1`（シェル）または `-Version 1.1.3-preview.1`（PowerShell）によってその正確な開発リリースが選択され、`X.Y.Z` によって利用可能な場合に安定版リリースが選択されます。タグにはプレビューサフィックスが含まれますが、インストーラーのファイル名には数値のアプリケーションバージョン（`1.1.3`）が使用されます。`--no-start` / `-NoStart` は、アプリケーションを起動せずにインストールします。

パッケージには、アプリケーションランタイムとメディアツールが含まれています。Linux デスクトップパッケージでは、必要なデスクトップライブラリをインストールするようにシステムのパッケージマネージャーに要求することもあります。

<a id="update-and-remove"></a>
## 更新とアンインストール

The same removal method applies whether a script or a binary installer installed the package. macOS script installs go to `~/Applications`; dragging from the DMG normally installs to `/Applications`. [Removal by installation method](STOP_AND_UNINSTALL.md#remove-by-installation-method) lists both locations, Linux commands, Docker, systemd and source removal. Keep your data unless you deliberately choose to erase it.

完全な停止、Windows のアンインストール動作、プログラム/データの場所、およびプロセスを実行し続ける古いインストーラーからの回復については、[FlintEye の停止とアンインストール](STOP_AND_UNINSTALL.ja.md)を参照してください。

更新する前に **Quit FlintEye** を選択してください。構成/インベントリをバックアップし、ロールバック用に以前のインストーラーを保持してください。
置換パッケージをインストールして再起動します。ユーザーデータはインストールディレクトリの外にあります。
macOS コマンドインストーラーは、以前のアプリを `FlintEye.previous.app` として保持します。後続のアップグレードの前に、そのバックアップを脇に移動してください。

通常の削除では、録画と設定が保持されます。Windows のアンインストーラーには、デフォルトで「いいえ」とするデータ削除のプロンプトが個別に用意されています。
手動でデータを削除する前に、[データの場所](DISTRIBUTION.ja.md#recording-lifecycle)を参照してください。


## 1.2.0 UNDER DEVELOPMENT インストーラーの確認

次回の開発ビルドでは、管理者パスワードフォームにブラウザを使用します。初回起動で信頼するネットワークを選びます。起動後の画面にローカルURLと使い捨てコードが表示され、LAN HTTPSの準備ができた場合は別端末用のURLと証明書の案内も表示されます。再インストール後に既存のアカウントがリセットされることはありません。クリーンなプロファイル、保持されたプロファイル、および未完了のプロファイルを使用して、ワンコマンドインストーラーとスタンドアロンインストーラーを比較してください。Linuxの自動インストールでは、ダウンロードの前にsudoとパッケージマネージャーがチェックされます。Windowsの削除処理では、まず録画を終了し、アンインストールデータのロックを確認します。ロックが報告された場合でも、unins000.datを削除する権限があるとは限りません。「[1.2.0 acceptance](DEVELOPMENT_1_2_0.ja.md)」および「[LAN setup](LAN_ACCESS.ja.md)」を参照してください。公開済みの1.1.3インストーラーに変更はありません。
