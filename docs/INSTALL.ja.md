<a id="install-flinteye"></a>
# FlintEye のインストール

[English](INSTALL.md)

[Documentation](README.ja.md)

**UNDER DEVELOPMENT.** 現在、公開リポジトリではソースコードを提供しています。公開インストーラーを準備中です。最初のリリース予定は `v1.1.3-preview.1` です。現在は [ソースセットアップ](MANUAL_INSTALL.ja.md)、[ローカルの M1 DMG ビルド](LOCAL_MACOS_BUILD.ja.md)、または [開発用 Docker](DOCKER.ja.md#build-the-development-image) をご利用ください。テスト済みダウンロードについては [Releases](https://github.com/noguhiro2002/FlintEye/releases) をご確認ください。以下の手順は、公開プレビューが利用可能になった後のパッケージ版インストールについて説明しています。[受け入れチェック](ACCEPTANCE.ja.md) および [既知の問題](KNOWN_ISSUES.ja.md) も参照してください。

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
32ビットシステムはサポートされていません。カメラの台数とパフォーマンスは、ハードウェアとストリームに依存します。

<a id="desktop-installation"></a>
## デスクトップのインストール

- **Windows:** EXE を開き、セットアップに従って管理者パスワードを選択します。インストールはユーザーごとに行われ、スタートメニューのエントリが作成されます。
- **macOS:** DMG を開き、FlintEye を Applications フォルダーにドラッグして開きます。ワンコマンドインストーラーは、個人の `~/Applications` フォルダーを使用します。
- **Linux:** パッケージマネージャーで DEB/RPM を開き、アプリケーションメニューから FlintEye を起動します。パッケージのインストールには管理者権限が必要です。

コマンドインストーラーは CPU を選択し、1つの固定リリースのパッケージをダウンロードして、その SHA-256 を検証します。
コンピュータ上でソフトウェアをコンパイルすることはありません。アップグレードする前に、実行中の FlintEye インスタンスを終了してください。
無人の Linux サーバーの場合は、デスクトップ UI を起動せずにインストールし、[systemd ガイド](DISTRIBUTION.ja.md#systemd)に従ってください。

<a id="included-media-tools-and-macos-recovery"></a>
## 付属のメディアツールと macOS の復旧

デスクトップパッケージには **MediaMTX、FFmpeg、FFprobe** が含まれています。個別の Homebrew や MediaMTX のインストールは不要です。macOS アプリでは、実行ファイルは `FlintEye.app/Contents/Frameworks/bin/` にあります。以前のプライベート ARM64 ビルドは検査され、3つすべてが含まれていました。

以前のプライベートな 1.1.0/1.1.1 macOS インストーラー（公開ダウンロードではありません）は、保存された設定に一時的な `AppTranslocation` パスを保持してしまうことがあります。そのディレクトリが消滅すると、MediaMTX はバンドルされているにもかかわらず起動できなくなります。UI に **Media server is unavailable** と表示され、カメラパブリッシャーが繰り返し再起動して、USB カメラのオンとオフが切り替わる場合があります。これは、`failed to start mediamtx:direct`、`FileNotFoundError`、および古い `AppTranslocation` のパスを含む `orchestrator.log` エントリと一致します。プロセスが一度も起動しなかったため、`mediamtx.log` が存在しないこともあり得ます。

これら既存のインストーラーの場合:

1. メニューバーアイコンを使用して Quit FlintEye を行います。完全な `FlintEye.app` を `/Applications` に配置し、DMG を取り出し、インストールされたアプリを開きます。ブラウザを閉じるだけでは FlintEye は停止しません。
2. 管理者としてサインインし、**Settings → Advanced** を開きます。ランタイム JSON で、`mediamtx.direct.command` の最初の項目のみを `/Applications/FlintEye.app/Contents/Frameworks/bin/mediamtx` に変更します。2番目の項目（あなたの `mediamtx.yml` パス）およびその他のすべての設定は変更しないでください。個人の Applications フォルダーの場合は、`~` ではなく、完全な `/Users/YOUR_NAME/Applications/...` パスを使用してください。
3. **Replace Runtime & Restart** をクリックします。MediaMTX のステータスを確認し、Live View、録画、再生を再試行します。この回避策を使用している間は、アプリをその場所に維持してください。

復旧のために `runtime.json` やデータディレクトリを削除しないでください。そこにはアカウントと設定が含まれています。別のデータディレクトリを選択していない場合、ログは `~/Library/Application Support/FlintEye/logs/` にあります。それでも起動に失敗する場合は、`orchestrator.log` と、存在する場合は新しいエラーに関する `mediamtx.log` を確認してください。

ソースの修正により、起動のたびに現在のアプリの場所からバンドルされた実行ファイルが解決され、ユーザー設定が保持されるようになります。また、ログイン自動起動のための一時的な実行ファイルパスの保存も停止されます。既存のリリース DMG は再ビルドまたは置き換えられていません。それらの自動修正には新しいインストーラーが必要です。ネイティブ macOS および物理カメラのチェックは保留中です。

GitHub Actions を使用せずに独自の M1 Mac で更新されたソースをテストするには、[ローカル DMG ビルドガイド](LOCAL_MACOS_BUILD.ja.md)に従ってください。これには、起動時の修復と統合された Settings インターフェイスが含まれており、既存のリリースダウンロードは変更されません。

<a id="unsigned-packages"></a>
## 署名なしパッケージ

初期の Windows パッケージには発行元の署名がありません。このリポジトリから想定したパッケージをダウンロードしたことを確認してください。
Windows が許可する場合は、SmartScreen が表示するアプリケーションごとの確認を使用してください。

macOS プレビューパッケージは、Developer ID による公証なしのアドホック整合性署名を使用しています。ビルドは現在、古いライセンスバンドルに誤ってコピーされたテスト/デバッグバイナリを含め、無効なバンドル署名を拒否します。有効なアドホック署名であっても、信頼できる発行元を確立するわけではありません。クリーンなマシンでは Gatekeeper による拒否が想定されます。ダウンロードしたアプリの最初の起動は、明示的な受け入れチェックのままです。[Apple によるアプリチェックの説明](https://support.apple.com/102445) および [署名の検証](https://developer.apple.com/library/archive/technotes/tn2206/) を参照してください。
アプリを開こうとした後、macOS が **システム Settings → プライバシーとセキュリティ → このまま開く** を要求する場合があります。
Gatekeeper をグローバルに無効にしたり、インストアラー スクリプトで隔離属性を削除したりしないでください。
管理対象のコンピューターでは、管理者の支援が必要になる場合があります。

<a id="install-a-specific-version"></a>
## 特定のバージョンのインストール

公開プレビューが利用可能な場合は、その正確なリリースからインストーラーまたはコマンドスクリプトを直接ダウンロードしてください。プレビューリリースは、GitHub の `releases/latest` URL では返されません。

そのリリースから `install.sh` または `install.ps1` をダウンロードし、ローカルで実行します。
生成される各スクリプトは、自身のリリースバージョンを固定します。オプションの `--version 1.1.3-preview.1` (シェル) または `-Version 1.1.3-preview.1` (PowerShell) により、その正確な開発リリースが選択されます。`X.Y.Z` は、利用可能な場合に安定版リリースを選択します。タグにはプレビューサフィックスが含まれますが、インストーラーのファイル名には数値のアプリケーションバージョン (`1.1.3`) が使用されます。`--no-start` / `-NoStart` は、アプリケーションを起動せずにインストールします。

パッケージには、アプリケーションランタイムとメディアツールが含まれています。Linux デスクトップパッケージでは、必要なデスクトップライブラリをインストールするようにシステムのパッケージマネージャーへの要求も行われます。

<a id="update-and-remove"></a>
## アップデートと削除

完全な停止、Windows のアンインストール動作、プログラム/データの場所、およびプロセスを実行したままにする古いインストーラーからの復旧については、[FlintEye の停止とアンインストール](STOP_AND_UNINSTALL.ja.md)を参照してください。

アップデート前に **Quit FlintEye** でアプリを終了してください。設定/インベントリをバックアップし、ロールバック用に前のインストーラーを保持してください。
代替パッケージをインストールして再起動します。ユーザーデータはインストールディレクトリの外にあります。
macOS コマンドインストーラーは、前のアプリを `FlintEye.previous.app` として保持します。後続のアップグレードの前に、そのバックアップを別の場所に移動してください。

通常の削除では、録画と設定が保持されます。Windows のアンインストーラーには、デフォルトで「いいえ」のデータ削除プロンプトが個別に用意されています。
手動でデータを削除する前に、[データの場所](DISTRIBUTION.ja.md#recording-lifecycle)を参照してください。
