<a id="community-distribution"></a>
# コミュニティ配布

[English](DISTRIBUTION.md)

<a id="user-installation"></a>
## ユーザーインストール

デスクトップパッケージには、Python、コンパイル済みのWeb UI、FFmpeg、およびMediaMTXが含まれています。
ユーザーがPython、Node.js、npm、Dockerをインストールする必要はありません。

Windowsでは、対応する `FlintEye-<version>-windows-<arch>-setup.exe` を実行し、インストーラーかスタートメニューからFlintEyeを起動します。macOSではDMGから `FlintEye.app` をApplicationsフォルダにコピーして開きます。Linuxでは、DEBまたはRPMをインストールし、アプリメニューから起動します。

コミュニティ版にはDeveloper ID署名・公証とWindowsのパブリッシャー署名がありません。macOSでは、アプリごとに **プライバシーとセキュリティ → このまま開く** 操作が必要な場合があります。ARM64用のmacOSバンドルには、整合性確認用のアドホック署名を付けています。

プレビュー6から、デスクトップ版はブラウザを開き、一度限りのセットアップ許可を渡します。`admin` のパスワードを12〜1024文字で決め、確認欄にも入力します。途中で閉じた場合は、アプリの **Open FlintEye** から再開してください。トークンを手動で入力する場合は **Address and setup assistance** を使います。パスワードはローカルでハッシュ化し、インストーラーの引数やログから除外します。

セットアップ後は **Settings → Basic → Cameras** で USB・IP カメラを設定します。入門ガイドは **Information → Getting started** から開き直せます。閲覧者を追加するときは **Settings → Basic → Runtime & access → Viewer access** で viewer のパスワードを設定します。変更すると既存のセッションが無効になります。

Settings はデスクトップ、Docker、ソース版で共通です。**Settings → Basic → Recording** で保存先・容量・保持期間を設定します。イベント録画と API キーは **Settings → Advanced → Integrations & API**、更新確認と診断情報は **Information** にあります。Apple Silicon 上のローカルビルドは [DMG ビルドガイド](LOCAL_MACOS_BUILD.ja.md)を参照してください。

ブラウザを閉じても監視は実行されたままになります。Windows/macOSのデスクトップメニューから、FlintEyeを開く、開始/停止/Restart monitoring、ログ、ログイン時起動、および Quit FlintEye を利用できます。Linuxには、コンパクトなコントロールウィンドウと、サポートされている環境でのトレイアイコンがあります。Stop monitoring により設定とAPIが利用可能な状態に維持され、「終了」ですべてが終了します。「起動時に常に監視を再開する」が有効になっていない限り、停止の設定は記憶されます。[監視コントロール](MONITORING.ja.md)を参照してください。

ログイン時の自動起動は、現在のデスクトップユーザーとインストールに属します。監視中/ファイナライズ中は自動スリープが禁止され、停止時に解除されます。手動でのスリープ/ログアウト/シャットダウンにより監視が中断されます。Linuxでの禁止には、動作中のsystemd/logindセッションが必要です。Docker/systemd/ヘッドレス実行では、デスクトップコントロールやログイン登録は作成されません。

FlintEye は通常 `http://127.0.0.1:18080` でローカル接続を受け付けます。LAN・VPN の別端末から見る場合は **Settings → Basic → Runtime & access** で HTTPS を有効にし、保存して再起動します。閲覧端末にこのインストールの CA を登録すると、HTTPS の接続先でログイン・API・映像を利用できます。ローカル HTTP と内部 MediaMTX はループバックに保ち、選んだ接続元から HTTPS の TCP ポートと WebRTC の UDP 8189 を許可します。[LAN と証明書の設定](LAN_ACCESS.ja.md)

管理者が用意するリバースプロキシを使う場合は、[既存プロキシの手順](LAN_ACCESS.ja.md#headless-and-existing-proxy-deployments)を参照してください。

<a id="recording-lifecycle"></a>
## 録画のライフサイクル

デフォルトの保持期間は7日間です。初期クォータは、50 GB（十進法）と、選択されたフォルダの利用可能なバイト数の半分とのうち小さい方になります。この提案値は保存されるものであり、継続的にサイズ変更されるわけではありません。ユーザーはクォータを変更できます。ストレージの選択はインストールPC上でネイティブに行われ、リモート管理者は絶対サーバーパスを入力します。

どちらの制限に先に達した場合でも、最も古い完了済みの録画が削除されます。7日間というのは最大値であり、保証ではありません。完了フックは、SQLiteインベントリにセグメントを登録します。サイズとmtime（更新時刻）が一致している、その登録済みのファイルのみがFlintEyeによって削除されます。アクティブ、未登録、またはインポートされたファイルは削除されません。MediaMTXの独立した有効期限による削除はこのモードでは無効になります。再生コピーは、録画フォルダ外のプライベートで制限された一時キャッシュを使用するようになりました。`recording.playback_cache_max_bytes` のデフォルトは2 GBであり、より大きなセグメントのために高度なJSONで増やすことができます。キャッシュへの書き込みでは、設定された空き容量の予約分に加えて256 MBが保持されます。収まらないセグメントは再生用としては拒否されますが、オリジナルの録画は管理者がダウンロードできるように保持されます。

録画フォルダ内に `.playback_cache` を使用していた開発版のインストールをアップグレードする前に、FlintEyeを停止し、その古いキャッシュディレクトリを削除してください。アクティブなフォルダが消失した場合や、クリーンアップ後も空き容量が1 GB未満のままの場合、録画は一時停止されバナーが表示されます。条件がクリアされると再開されます。クォータの適用は30秒ごとに実行され、アクティブなセグメントによる一時的なオーバーシュートを許可します。ディスクに十分な空き容量を確保してください。インポートされたファイルや未登録のファイルは手動でのクリーンアップが必要になる場合があります。完了フックが実行される前のクラッシュにより、そのようなファイルが残る可能性があります。

録画フォルダを変更しても、録画は移動しません。古いフォルダは、独自の以前の保持期間/クォータ設定を保持します。デフォルトでは引き続き表示されます。「**以前の場所からの録画を表示する**」を無効にすると、それらの再生エンドポイントとリストエントリは非表示になりますが、保持は停止されません。異なるルートにある同じファイル名は、異なる録画IDを持ちます。ディスクを取り外すとその録画は利用できなくなりますが、再接続すれば再びアクセスできるようになります。

Settings、インベントリ、ログ、および録画は、インストールディレクトリの外側にあります：

* Windows: `%LOCALAPPDATA%\FlintEye`
* macOS: `~/Library/Application Support/FlintEye`
* Linuxデスクトップ: `${XDG_DATA_HOME:-~/.local/share}/flinteye`
* systemd: `/var/lib/flinteye`
* Docker: `/data`

アプリケーションのアンインストールでは、デフォルトでデータが保持されます。Windowsのアンインストーラーには、デフォルトで「いいえ」となっている、デフォルトのユーザーデータフォルダを消去するための個別の確認オプションが用意されています。他のプラットフォームでデータを明示的に消去するには、FlintEyeを停止し、ログイン自動起動のエントリを削除して、選択したデータ/録画フォルダを削除してください。永続化されたデータを削除すべき場合を除き、`docker compose down -v` を使用しないでください。

<a id="administrator-deployments"></a>
## 管理者向けデプロイ

<a id="docker-linux-x86-64--arm64"></a>
### Docker (Linux x86-64 / ARM64)

クローンを作成せずに公開済みイメージを使用する場合は、[Dockerガイド](DOCKER.ja.md)に従ってください。
以下のコマンドは、プライベートな開発用チェックアウトをビルドします。

```sh
docker compose -f deploy/compose.dev.yaml up -d --build
docker compose -f deploy/compose.dev.yaml exec flinteye cat /data/setup-token
```

SSHトンネル（`ssh -L 18080:127.0.0.1:18080 <server>`）を使用し、`http://127.0.0.1:18080` を開いて、1回限りのセットアップトークンを入力し、管理者パスワードを選択します。トークンは所有者のみの権限で保存され、セットアップ後に削除されます。ログには書き込まれません。これは、ヘッドレスなsystemdインストールの初期アカウントフローでもあります。Composeファイルは、LANでのONVIF検出およびWebRTCにLinuxホストネットワークを使用します。オプションのUSBデバイス/ビデオグループのマッピングはそのファイルに示されています。Docker DesktopのUSBサポートは含まれていません。テスト済みのamd64/arm64アーカイブを配布するにはリリースワークフローを使用してください。公開時の再ビルドは行わないでください。

データボリュームはUID/GID 10001に属します。バインドマウントはそのIDで書き込み可能である必要があります。コンテナフォルダのパスはコンテナ内のパスです。追加の録画ディスクはすべて明示的にマウントしてください。ビルド済みイメージにはMediaMTXバイナリが含まれているため、オーケストレーターがその起動と停止を管理します。

<a id="systemd"></a>
### systemd

`/opt/flinteye` にあるネイティブLinuxバンドルをインストールし、`flinteye` システムユーザー/グループを作成します。`/etc/systemd/system/` の下に `packaging/flinteye.service` をインストールします。USBキャプチャにはホストの `video` グループが必要です。別のデバイスグループを使用するホストではこれを適宜変更してください。

新規プロファイルの初回起動時から LAN HTTPS を利用する場合は、[サービスに接続先の環境変数を設定](LAN_ACCESS.ja.md)します。USBマイクを使う場合は、ホストのaudioグループへのアクセスも必要です。

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now flinteye
sudo cat /var/lib/flinteye/setup-token
```

稼働中の接続先は `sudo -u flinteye /opt/flinteye/FlintEye --headless --data-dir /var/lib/flinteye --connection-info` で確認できます。そのURLを開き、使い捨てコードを入力します。

デスクトップインスタンスとsystemdインスタンスの間で、実行中のデータディレクトリやポートを共有してはなりません。サービスはログインなしで起動し、デスクトップアプリケーションはログイン後に起動します。

### サーバーデプロイの削除

systemdの場合、まず `sudo systemctl disable --now flinteye` を実行します。手動でインストールしたユニットとデプロイメントのドロップインを削除し、`sudo systemctl daemon-reload` を実行してから、パッケージまたは専用プログラムバンドルを削除します。明示的に消去したい場合を除き、`/var/lib/flinteye`、カスタムデータ、および外部録画は保持してください。[systemdの完全削除](STOP_AND_UNINSTALL.ja.md#systemd)

Dockerの場合、それを開始したのと同じComposeファイル、デプロイメントディレクトリ、およびプロジェクトオプションを使用します。`docker compose down` はデータを保持します。[Docker削除ガイド](STOP_AND_UNINSTALL.ja.md#docker-compose)には、デスクトップ/開発用のバリエーションとオプションのイメージクリーンアップが記載されています。[データ消去とLAN信頼のクリーンアップ](STOP_AND_UNINSTALL.ja.md#permanently-erase-data-optional)は個別のステップです。

<a id="building-installers"></a>
## インストーラーのビルド

自動ビルド、ソース/ライセンスアーカイブ、およびGHCR公開については、[リリースガイド](RELEASING.ja.md)を使用してください。

ターゲットOSおよびCPUごとに個別にビルドします。Windows/macOSではPython 3.14.10とNode.js 22を使用します。LinuxのDockerビルダーは、固定されたPython 3.13.18のソースをコンパイルします。既存のソースワークフロー（`tools/start_orchestrator_stack.py`）も引き続き利用できます。

[文書化されたビルドツール](RELEASING.ja.md#local-native-build)を指定して `bash packaging/build_vendor.sh` を実行します。
これにより、ターゲットCPU用の `vendor/bin/ffmpeg[.exe]`、`vendor/bin/ffprobe[.exe]`、および `vendor/bin/mediamtx[.exe]`、さらに通知、対応するソース、およびビルド設定の準備が整います。FFmpegは `drawtext` および `libx264` をサポートしている必要があります。選択されたバイナリに必要なランタイムライブラリをすべてバンドルしてください。x86-64のバイナリをARM64パッケージに混入させないでください。FFmpegとFFprobeには、concatデマルチタイーおよびHTTP/HTTPS/RTSPサポートを含める必要があります。カメラのURLは、プロセス引数ではなく、プライベートな単一入力マニフェストを通じて配信されます。ビルドでは、実際のベンダーバイナリを使用してパッケージングする前に、認証されたHTTPおよびRTSPの取り込み、プロービング、スナップショットをテストします。ソースインストールでも同じプライベート入力パスを使用します。資格情報やクエリトークンを含むカスタムパブリッシャーURLは拒否されます。バンドルされているループバックのMediaMTXパブリッシャーエンドポイントを使用してください。ランタイムの資格情報とプライベートマニフェストは、Windowsにおけるインストールユーザーのプライベートプロファイル/一時ディレクトリのACLに依存しています。HTTPSのONVIFエンドポイントは信頼された証明書を提示する必要があります。プライベートカメラCAを使用する管理者は、`REQUESTS_CA_BUNDLE` を通じてそのバンドルを提供できます。

```sh
python -m pip install -c packaging/constraints.txt -r requirements.txt -r packaging/requirements-build.txt
python packaging/build_bundle.py --vendor vendor
```

バンドルは `dist/FlintEye` にあります。macOSではさらにアプリとDMGが生成されます。スクリプトはベンダーのハッシュを `dist/vendor-sha256.json` に記録します。Windowsの場合は、`/DAppVersion=X.Y.Z /DAppArch=amd64`（または `arm64`）を指定して `packaging/windows.iss` に対してInno Setup 6を実行します。Linuxの場合は、nFPMをインストールして以下を実行します：

```sh
VERSION=$(python packaging/release.py version) ARCH=amd64 nfpm package --config packaging/nfpm.yaml --packager deb --target dist/
VERSION=$(python packaging/release.py version) ARCH=amd64 nfpm package --config packaging/nfpm.yaml --packager rpm --target dist/
```

ARMビルドには `ARCH=arm64` を使用してください。より新しいglibc要件の導入を避けるため、RPMはRocky Linux 9上でビルドしてください。DEBはその最小ターゲットに対してビルドしてください。Linuxデスクトップシステムには、グラフィカルセッションとTk/X11ライブラリが必要です。完全なツールチェーンのネイティブARM64での可用性は、公開前に検証する必要があります。

プレビュー版は **Information → Check for updates** で、より新しいプレビューや安定版を確認します。安定版インストーラーはプレビューを無視します。ソースチェックアウトはGitで更新されます。FlintEyeがアップデートを自動的にダウンロードまたはインストールすることは決してなく、アップデートの確認によって録画が再起動されることもありません。Quit FlintEyeでの終了、設定/インベントリのバックアップ、代替パッケージのインストール、および再起動を行ってください。ロールバックのために以前のパッケージを保持してください。すべてのデータディレクトリ/ボリュームを維持してください。アップグレード中も既存の設定は維持されます。以前の開発版インストールで `api.host` が `0.0.0.0` に設定されている場合は、それを `127.0.0.1` に変更して再起動し、LANアクセスには前述のHTTPSプロキシを使用してください。録画を再開する前に、FlintEyeが停止している状態で古い共有の `.playback_cache` を削除してください。

<a id="release-acceptance-matrix-not-a-claim-of-completed-certification"></a>
## リリース受入マトリックス（完了した認証の主張ではありません）

* Windows 10 22H2およびWindows 11：x86-64、ARM64。
* Ubuntu 24.04 LTSおよびそれ以降のテスト済みLTSリリース：x86-64、ARM64。
* Rocky Linux最新の9.xおよび10.x：x86-64、ARM64。
* macOS 14およびそれ以降のテスト済みリリース：Intel、Apple Silicon。
* Raspberry Pi 4/5：64ビットRaspberry Pi OS。リリース前に正確なOSイメージを検証してください。

各ターゲットについて、Python/Nodeなしでのクリーンインストール、パスワード設定/キャンセル、USBおよびIP入力、2台目のLANデバイスからのライブビデオ、録画/再生、非ASCII文字のユーザー名/フォルダ名、フォルダの変更、ボリュームの取り外し、ディスク制限、ログイン時起動、ブラウザを閉じることと終了の違い、重複起動、およびアップグレード/アンインストールのデータ保持をテストしてください。すべての外部メディアリスナーが認証されていないアクセスを拒否することを検証してください。実際のカメラでPiのパフォーマンスをテストし、カメラの台数が一律であると約束しないでください。

<a id="validation-and-development-status"></a>
## 検証および開発ステータス

**UNDER DEVELOPMENT.** [Preview 10 のインストーラー](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.2.0-preview.10)と[固定版の GHCR イメージ](DOCKER.ja.md)を公開しています。[実機チェックリスト](RELEASE_CHECKLIST_1_2_0.ja.md)に、テスト対象のコミット、ビルド・公開経路の結果、残る実機確認を記録しています。

自動化されたチェックでは、セットアップ/認証、ストレージの保持期間、再生の境界、ワーカーの読み込み、メディアプロセスのクリーンアップ、インストーラー/リリースの整合性、およびプレビューバージョンの比較がカバーされています。フロントエンドはすべてのプラットフォームで共有ソースからコンパイルされます。ネイティブビルドジョブは合成メディアを使用してインストール済みパッケージをテストしますが、実際のカメラの動作やすべての最小OSを保証することはできません。

公開プレビューには、完全なビルドの成功と対応ソース・ライセンスの確認が必要です。安定版の配布前には[受け入れチェックリスト](ACCEPTANCE.ja.md)を完了します。公開プレビューでは、macOS の初回起動承認や実機の未確認項目を結果に記載します。ブラウザーを閉じても監視は続き、アプリの終了時には所属する API とメディア処理が停止する必要があります。