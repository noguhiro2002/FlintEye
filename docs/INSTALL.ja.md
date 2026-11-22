<a id="install-flinteye"></a>
# FlintEye のインストール

[English](INSTALL.md)

[Documentation](README.ja.md)

**UNDER DEVELOPMENT.** [Quick Install](../README.ja.md#quick-install) または [該当するリリース](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.2.0-preview.5) から **1.2.0-preview.5** をインストールしてください。どちらの方法でも、同じテスト済みアプリケーションが使用されます。正確なプレビュー版とソースコミットについては、**Information → System** を確認してください。自動パッケージチェックは合格しましたが、実機での検証は現在進行中です。以前にダウンロードした 1.1.3 インストーラーやスクリプトは、その旧バージョンに固定されたままです。[Source setup](MANUAL_INSTALL.ja.md)、[local M1 DMG builds](LOCAL_MACOS_BUILD.ja.md)、および [development Docker](DOCKER.ja.md#build-the-development-image) は引き続き利用可能です。

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
- **Linux:** システム全体に入れる場合は、パッケージマネージャーでDEB/RPMを開きます。この方法には管理者権限が必要です。ホームフォルダに入れる場合は、[Linuxの `--user` 手順](../README.ja.md#install-without-administrator-privileges)に従ってください。

コマンドインストーラーは CPU を選択し、固定された1つのリリースのパッケージをダウンロードして、その SHA-256 を検証します。
コンピューター上でソフトウェアをコンパイルすることはありません。アップグレードする前に、実行中の FlintEye インスタンスを終了してください。
無人 Linux サーバーの場合は、デスクトップ UI を起動せずにインストールし、[systemd ガイド](DISTRIBUTION.ja.md#systemd)に従ってください。

<a id="included-media-tools-and-macos-recovery"></a>
## 付属のメディアツールと macOS のリカバリ

<a id="screen-recording-requests-in-older-previews"></a>
### 以前のプレビュー版における画面収録リクエスト

FlintEye はデスクトップを録画しません。以前のカメラ検出では FFmpeg の `Capture screen` 入力が含まれており、カメラモードの照会中にこれらを開いていたため、繰り返しの **画面収録 (Screen Recording)** 許可ダイアログが発生していました。**1.2.0-preview.3** では、スクリーン入力はプローブ（調査）前に除外されます。また、保存されたカメラインデックスはキャプチャ前に確認されるため、削除されたカメラが古いインデックスを使って画面を選択することはありません。OBS 仮想カメラは引き続きカメラ入力としてサポートされます。FlintEye に画面収録の許可を与える必要はありません。マイクアクセスは別個のものであり、カメラの音声が有効な場合にのみ使用されます。実機での品質保証の一環として、Mac 上で繰り返しプロンプトが表示されないことを確認してください。

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

Finder が **ファイルが見つかりません** と報告しても `Contents/MacOS/FlintEye` が存在する場合は、OS の信頼拒否も考えられます。報告された M1 のケースでは、実行ファイルとバンドル署名は有効でしたが、`amfid` がアドホック署名を拒否し、直接実行が終了コード 137 で終了しました。アプリごとの承認を試してください。公証の欠如は、MediaMTX の再インストールやアカウント/設定の削除では修復されません。インストーラーのメッセージは、ファイルのインストール、起動リクエスト、および初回起動の許可を区別するようになりました。ビルド時のテストでは、macOSのCI上で同様のOSによる拒否が確認されており、インストール後のAPI/GUIチェックは承認されるまで未実行のままとなります。[インストールライフサイクルチェック](INSTALLATION_QA.ja.md)を参照してください。

<a id="install-a-specific-version"></a>
## 特定のバージョンのインストール

正確なプレビューリリースからインストーラーまたはコマンドスクリプトをダウンロードします。プレビューリリースは GitHub の `releases/latest` URL では返されません。

そのリリースから `install.sh` または `install.ps1` をダウンロードして、ローカルで実行します。
生成される各スクリプトは、自身のリリースバージョンを固定します。オプションの `--version 1.2.0-preview.5`（シェル）または `-Version 1.2.0-preview.5`（PowerShell）によってその正確な開発リリースが選択され、`X.Y.Z` によって利用可能な場合に安定版リリースが選択されます。タグにはプレビューサフィックスが含まれますが、インストーラーのファイル名には数値のアプリケーションバージョン（`1.2.0`）が使用されます。`--no-start` / `-NoStart` は、アプリケーションを起動せずにインストールします。

パッケージには、アプリケーションランタイムとメディアツールが含まれています。Linux デスクトップパッケージでは、必要なデスクトップライブラリをインストールするようにシステムのパッケージマネージャーに要求することもあります。

<a id="update-and-remove"></a>
## 更新とアンインストール

[READMEの削除手順](../README.ja.md#uninstall)から、[インストール方法に合った手順](STOP_AND_UNINSTALL.ja.md#remove-by-installation-method)を選んでください。macOSのスクリプト版は既定で `~/Applications` に入ります。DMGからコピーした場合は、実際にコピーしたフォルダから削除してください。

このガイドは、Windows 10/11、Linux DEB/RPM、Docker、systemd、およびソース環境をカバーしています。通常の削除ではアカウント、設定、録画が保持されます。[恒久的なデータ消去](STOP_AND_UNINSTALL.ja.md#permanently-erase-data-optional)は個別の選択肢です。

完全な停止、Windows のアンインストール動作、プログラム/データの場所、およびプロセスを実行し続ける古いインストーラーからの回復については、[FlintEye の停止とアンインストール](STOP_AND_UNINSTALL.ja.md)を参照してください。

更新する前に **Quit FlintEye** を選択してください。構成/インベントリをバックアップし、ロールバック用に以前のインストーラーを保持してください。
置換パッケージをインストールして再起動します。ユーザーデータはインストールディレクトリの外にあります。
Linuxでパッケージ上の版番号が同じプレビューに更新する場合は、新しいリリースのコマンドインストーラーを使ってください。ダウンロードしたパッケージでインストール済みの版を差し替えます。
macOS コマンドインストーラーは、以前のアプリを `FlintEye.previous.app` として保持します。後続のアップグレードの前に、そのバックアップを脇に移動してください。

通常の削除では、録画と設定が保持されます。Windows のアンインストーラーには、デフォルトで「いいえ」とするデータ削除のプロンプトが個別に用意されています。
手動でデータを削除する前に、[データの場所](DISTRIBUTION.ja.md#recording-lifecycle)を参照してください。


## 1.2.0 開発インストーラーの確認

初回起動時に信頼するネットワークを選びます。1.2.0-preview.6から、デスクトップ版はこの端末のブラウザにセットアップ許可を渡します。ブラウザで管理者パスワードを設定してください。途中で閉じた場合は、アプリの **Open FlintEye** から再開します。手動入力用のトークンと接続先は **Address and setup assistance** で確認できます。設定を保持して再インストールした場合は、既存のアカウントでサインインします。ワンコマンド版と単体インストーラーを比較するときは、同じビルドの成果物を使います。[実機チェックリスト](RELEASE_CHECKLIST_1_2_0.ja.md) · [LAN接続手順](LAN_ACCESS.ja.md)
