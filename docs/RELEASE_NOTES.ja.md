<a id="flinteye-tag--status"></a>
# FlintEye @TAG@ — @STATUS@

[English](RELEASE_NOTES.md)

Application version: `@VERSION@` · Source commit: `@COMMIT@` · Build run: `@RUN_ID@`

@VALIDATION@

<a id="downloads"></a>
## ダウンロード

このリリースの「アセット」から、お使いのシステム用のインストーラーをダウンロードしてください：

| コンピューター | インストーラー |
| --- | --- |
| Windows x64 / ARM64 | `FlintEye-@VERSION@-windows-amd64-setup.exe` / `FlintEye-@VERSION@-windows-arm64-setup.exe` |
| macOS Intel / Apple Silicon | `FlintEye-@VERSION@-macos-amd64.dmg` / `FlintEye-@VERSION@-macos-arm64.dmg` |
| Ubuntu / Raspberry Pi OS (64-bit) | `FlintEye-@VERSION@-linux-amd64.deb` / `FlintEye-@VERSION@-linux-arm64.deb` |
| Rocky Linux | `FlintEye-@VERSION@-linux-amd64.rpm` / `FlintEye-@VERSION@-linux-arm64.rpm` |

Windows/macOSパッケージは未署名であり、公証されていません。`documentation.zip`にあるアプリケーションごとのOS確認手順に従ってください。アップグレード前に **Quit FlintEye** でアプリを終了してください。設定と録画データは保持されます。カメラアクセス、録画、再生、トレイ/GUIの動作、および最小サポートOSについては、引き続き実際のデバイスでの受入確認が必要です。

アーカイブには、英語および日本語のインストール・受入ガイド、該当する正確なLICENSE、サードパーティの通知、および対応するソースが含まれています。`SHA256SUMS`は、それ自身を除くすべての添付ファイルを網羅しています。`build-manifest.json`には、テストされた元のバンドルが記録されています。`distribution-manifest.json`は、このリリースで選択されたファイルとGHCRイメージダイジェストを識別します。公開用のワンコマンドインストールスクリプトは、プライベートなテストリリースでは省略されています。

<a id="container"></a>
## コンテナ

`linux/amd64`または`linux/arm64`には`ghcr.io/noguhiro2002/flinteye:@IMAGE_VERSION@`を使用してください。公開イメージは匿名でのプルを許可していますが、プライベートテストには認証されたGHCRログインが必要です。プレビューイメージにはコンテナの`latest`タグはありません。添付の`compose.yaml`と、`documentation.zip`のDockerガイドを使用してください。

<a id="changes-in-this-version"></a>
## このバージョンの変更点

- 設備から異常の発生時刻、さかのぼる秒数、カメラ ID を API に送ると、指定区間を別フォルダーに保存します。映像は **Recordings → Event recordings** で確認できます。[設定と API の使い方](USER_GUIDE.ja.md#event-recordings)
- macOS で監視を停止するときは、MediaMTX が録画中のセグメントを閉じるのを待ちます。完了通知が失われたファイルも、**Retry Stop** で再生できると確認できれば一覧に登録します。録画一覧は撮影時刻でもファイル更新時刻でも絞り込めます。
- カメラ追加時に録画と ONVIF の設定箇所が分かるようになりました。設定の保存が終わってから画面を切り替えます。Live View の操作が失敗した場合は理由を表示します。初回のネットワーク選択では、このコンピューターからの接続だけを許可する設定が初期値です。
- **Inspect camera** がMedia1・Media2のプロファイルからPTZ対応を確認します。自動検出を使う場合は、探索で見つからなければTapoのTCP 2020も試します。接続先が応答しない場合や、認証・証明書の検証に失敗した場合は、その理由を表示します。
- デスクトップメニューとDashboardで、監視状態と現在使える操作が一致します。保存先が復旧したら、**Retry Stop** で完了済みの録画を再登録できます。macOSではメニューを閉じてから **Force quit** の確認を表示し、承認すると進行中の停止処理を打ち切って終了します。
- USB・IPカメラの表示名をSettingsで変更できます。MediaMTXのパスを変更すると、録画とMultiviewで明示的に選んだパスも更新されます。録画済みのファイルは元の場所から再生できます。
- Windowsの録画処理が設定をUTF-8で読み込むようにしました。カメラ名に日本語などが含まれていても、録画を完了して終了できます。
- Linuxでは、管理者権限なしで `install.sh --user` によるインストールとアンインストールができます。アンインストール後も設定と録画は残ります。[インストールと削除の手順](INSTALL.ja.md)
- 登録済みの全API操作で権限と許可時の応答を確認します。Settingsの各操作・選択肢・入力範囲を台帳に記録しました。インストール検証では、合成映像とONVIF機器を使い、カメラの設定変更、Live View、Multiview、録画とPTZを確認します。[Actionsの検証結果の読み方](testing/CI_ACCEPTANCE.md)
- Windows・macOS・Linuxのデスクトップ版は、初回起動時にブラウザを開き、セットアップ許可を自動で渡します。管理者パスワードを設定すれば進めます。期限切れやサーバー版でトークンを手動入力するときも、画面で取得場所を確認できます。
- **Runtime & access** に、LANやVPN経由で他の端末から接続するための設定を明記しました。稼働中のHTTPSアドレス、再起動待ち、直近に拒否した接続元IPを確認できます。ポート競合の表示と、証明書の警告や `ERR_SSL_PROTOCOL_ERROR` の対処手順も更新しました。
- WindowsでUSBカメラを起動する際に、FFmpegのエンコーダー一覧の取得で停止する不具合を修正しました。ワーカーのエラーはログで確認できます。USB音声は管理済みUSBカメラの欄に移し、IPカメラ設定は狭い画面でも枠内に収まるよう調整しました。
- LAN経由でサインインした管理者も、IPカメラを追加・削除できます。MediaMTX本体の設定はサーバー上で変更します。
- macOSでは、配下のプロセスが終了済みか確認してから終了処理を続けます。まだ動いているプロセスの停止に失敗した場合は、終了を再試行できます。
- Windowsでは、録画処理が設定ファイルを一時的に開いている間、保存を再試行します。保存できなかった場合は、直前の設定を保持します。
- インストール検証では、合成カメラ2台を追加し、Live Viewで映像が進むこと、Multiviewで両方の映像が見えること、カメラを削除して再追加できることを確認します。Linuxのソース版では、USB入力を模した映像を実際のUSBワーカーに通し、合成IPカメラと同時にテストします。ビルドごとの実施結果は `QA-RESULTS.json` で確認できます。[実機チェックリスト](RELEASE_CHECKLIST_1_2_0.ja.md)

<a id="license"></a>
## ライセンス

個人、ならびに大学、公的研究機関、企業を含む非営利または営利組織は、個人用または内部目的でFlintEyeを使用および変更できます。プロバイダーは、顧客所有または顧客制御のインフラストラクチャ（顧客の契約クラウド環境を含む）上で、インストール、設定、変更、運用、保守に対する料金を請求し、FlintEye自体の料金を請求することなく必要なコピーを提供できます。FlintEyeまたはその改変版の販売、バンドル内でのソフトウェア料金の請求、または有料ホステッドサービスの提供には、別途ライセンスが必要です。英語版LICENSEが効力を持ち、旧バージョンのサードパーティの権利および付与内容は変更されません。
