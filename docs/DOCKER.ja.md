<a id="docker-compose"></a>
# Docker Compose

[English](DOCKER.md)

[ドキュメント](README.ja.md) · [GHCR公開設定](RELEASING.ja.md#ghcr-setup)

Docker EngineとComposeプラグインがインストールされたLinuxサーバー上でこの手順を使用します。
イメージは `linux/amd64` および `linux/arm64` を対象としています。Windows/macOSでは、ネイティブのデスクトップパッケージを使用することが推奨されています。
ホストのネットワーク機能により、ONVIF検出とWebRTCが維持されます。Docker DesktopのUSB転送機能は含まれていません。

<a id="install-without-cloning"></a>
## クローンせずにインストールする

**UNDER DEVELOPMENT.** プレビューイメージは `ghcr.io/noguhiro2002/flinteye:1.2.0-preview.4` です。配布URLからのインストールおよび実機のテストのために、このバージョンが[パブリックGHCRパッケージ](https://github.com/users/noguhiro2002/packages/container/package/flinteye)に掲載されたら、プルコマンドを使用してください。自動パッケージチェックは通過しましたが、実機での受け入れテストは進行中です。これは安定版リリースではありません。[ローカルでのビルド](#build-the-development-image)を行うことも可能です。

公開されているパブリックイメージは、GitHubアカウントやトークンなしでプルできます。Dockerに期限切れの保存済み認証情報がある場合は、匿名でプルする前に `docker logout ghcr.io` を使用してください。管理者によるプライベートテストには、引き続き認証済みのアカウントと、`read:packages` を備えたクラシックトークンが必要です。これらは `docker login ghcr.io -u YOUR_GITHUB_USERNAME` のパスワードプロンプトに入力してください。トークンを `.env` やコマンド引数に入力しないでください。

同じバージョンのGitHub Releaseから [compose.yaml](https://github.com/noguhiro2002/FlintEye/releases/download/v1.2.0-preview.4/compose.yaml) を新しいディレクトリにダウンロードし、`.env` を作成します。

```dotenv
FLINTEYE_IMAGE=ghcr.io/noguhiro2002/flinteye:1.2.0-preview.4
```

プレビュー版には `latest` イメージタグがありません。上記のように正確なバージョンを固定し、ハードウェア用の[受け入れチェック](ACCEPTANCE.ja.md)を完了させてください。

そのディレクトリから以下を実行します。

```sh
docker compose pull
docker compose up -d
docker compose exec flinteye cat /data/setup-token
```

http://127.0.0.1:18080 を開き、1回限りのトークンを入力して管理者パスワードを作成します。
リモートサーバーの場合は、まずSSHトンネルを作成します。

```sh
ssh -L 18080:127.0.0.1:18080 your-server
```

セットアップトークンをIssueに投稿したり、パスワードをコマンド引数に入力したりしないでください。
その他のLANユーザー向けには、[HTTPSリバースプロキシ](DISTRIBUTION.ja.md#user-installation)を設定してください。
HTTP/API/MediaMTXリスナーはループバック上で動作し続けます。また、WebRTCにはUDP 8189も必要です。

<a id="finish-setup-over-https"></a>
### Finish setup over HTTPS

ComposeはLinuxのホストネットワークを使用します。新しいデータボリュームで起動する前に、`compose.yaml` と同じフォルダの `.env` にサーバーのIPと許可するネットワークを指定します。以下の値は実際の環境に置き換えてください。

```dotenv
FLINTEYE_LAN_ADDRESS=192.168.1.10
FLINTEYE_LAN_SOURCES=192.168.1.0/24
```

```sh
docker compose up -d --wait
docker compose exec flinteye python /opt/flinteye/flinteye.py --headless --connection-info
```

`/data/connection-guide` から公開証明書と手順書を閲覧端末にコピーします。サーバーで証明書の指紋を照合してから信頼し、表示されたHTTPSの接続先を開きます。管理者は `docker compose exec flinteye cat /data/setup-token` で使い捨てコードを取得し、ブラウザで入力します。LANを準備できない場合はローカルの接続先を使用します。既存のデータボリュームでは保存済みの接続設定を引き継ぎます。USBカメラのマイクも使う場合は、映像デバイスに加えて `/dev/snd` とホストのaudioグループをComposeで指定します。


## ストレージとカメラ

名前付きボリューム `flinteye-data` により、コンテナの置き換え後も設定、インベントリ、録画が保持されます。
プロセスはUID/GID 10001を使用します。バインドマウントされたフォルダは、そのIDで書き込み可能である必要があります。
Web UIで選択したパスは、コンテナ内のパスを指します。追加の録画ディスクは明示的にマウントしてください。

IPカメラにはネットワークアクセスが必要です。オプショナルのUSBマッピングは `compose.yaml` に示されています。ホストの実際のデバイスとビデオグループのGIDを選択してください。
オプションのネイティブRaspberry Pi CSIヘルパーはバンドルされていません。ARM64ビルドではUSB/IP入力が機能します。

<a id="update-and-rollback"></a>
## アップデートとロールバック

リリースノートを確認し、最初に設定とインベントリのバックアップを取ります。`.env` で固定されたバージョンを変更してから、以下を実行します。

```sh
docker compose pull
docker compose up -d
docker compose logs --tail=50 flinteye
```

コンテナを置き換えると、モニタリングが一時的に中断されます。アップデートが自動的に適用されることはありません。
ロールバックするには、`.env` 内の正確な以前の `ghcr.io/noguhiro2002/flinteye:VERSION` を元に戻し、`docker compose pull` と `docker compose up -d` を実行します。リリースで必要な場合は、対応する設定のバックアップを復元してください。アップグレードが検証されるまで、古いバージョンとその設定のバックアップを保持してください。

<a id="uninstall"></a>
## アンインストール

同じデプロイメントフォルダから、起動時に使用した同じ `.env` およびプロジェクトオプションを使用して以下を実行します。

```sh
docker compose down
```

これにより、データボリュームとバインドマウントされた録画ファイルを保持したまま、コンテナとそれらに付随するAPI/メディアプロセスが停止・削除されます。ダウンロードしたファイルを使用しているDocker Desktop環境では `docker compose -f compose.desktop.yaml down` を、チェックアウトしている場合は `docker compose -f deploy/compose.desktop.yaml down` を実行してください。開発イメージを使用している場合は、チェックアウトのルートから `docker compose -f deploy/compose.dev.yaml down` を実行してください。元の起動コマンドで使用したその他の `-f`、`-p` / `--project-name`、または `--env-file` オプションはそのまま維持してください。

通常の削除で `--volumes` / `-v` は追加しないでください。キャッシュされたイメージは個別に削除するまで残ります。イメージのクリーンアップについては[完全なDocker削除](STOP_AND_UNINSTALL.ja.md#docker-compose)を、録画や設定も完全に削除したい場合は[オプションのデータ完全消去](STOP_AND_UNINSTALL.ja.md#permanently-erase-data-optional)を参照してください。

<a id="build-the-development-image"></a>
## 開発イメージのビルド

リポジトリのチェックアウトから以下を実行します。

```sh
docker compose -f deploy/compose.dev.yaml up -d --build
docker compose -f deploy/compose.dev.yaml exec flinteye cat /data/setup-token
```

これによりローカルの `flinteye:development` イメージが作成されますが、公開はされません。
同じポートで開発インスタンスとインストール済みインスタンスを同時に実行しないでください。

<a id="if-the-mediamtx-download-times-out"></a>
### MediaMTXのダウンロードがタイムアウトする場合

`packaging/vendor.py` からの `TLS handshake operation timed out` エラーは、ビルドが上流のファイルをダウンロードできなかったことを意味します。これはコンパイラのエラーではなく、ネットワーク/ダウンロードの障害です。一時的な障害に対するダウンロードは最大3回まで再試行され、検証済みファイルが再利用されるようになりました。SHA-256およびTLS証明書のチェックは引き続き有効です。Goモジュール/ビルドキャッシュも重複する作業を削減します。

ホスト上でMediaMTXダウンロードキャッシュを準備するには、Python 3.11以降および最新のDocker Composeプラグイン（[2.17.0以降](https://docs.docker.com/reference/compose-file/build/#additional_contexts)）を使用して、チェックアウトのルートから次のコマンドを実行します。

```sh
python3 packaging/vendor.py media-cache
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

信頼できるFlintEyeビルドから対応するMediaMTXソースアーカイブをすでに持っている場合は、再度ダウンロードする代わりにその固定ファイルをインポートしてください。`MEDIA_SOURCE_ARCHIVE` を実際のアーカイブパスに置き換えてください。

```sh
python3 packaging/vendor.py media-cache --from-source-archive MEDIA_SOURCE_ARCHIVE
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

インポーターは、選択された3つのファイルを再利用する前に固定されたMediaMTX/HLSチェックサムと照合して検証します。任意のアーカイブパスを抽出することはありません。ソースのダウンロードは、どちらのCPUアーキテクチャでも機能します。別のバージョンのソースアーカイブは、そのチェックサムが現在のチェックアウトと一致する場合にのみ使用できます。

これによりバイパスされるのは、MediaMTXソース、HLSバンドル、およびライセンスのダウンロードのみです。ベースイメージ、システムパッケージ、Goモジュール、Pythonパッケージ、フロントエンドの依存関係には引き続きネットワークアクセスが必要です。それらが失敗した場合は、検証を無効にするのではなく、Dockerデーモン/ビルドのネットワークおよびプロキシ設定を確認してください。

このキャッシュを使用して再ビルドする場合は、`FLINTEYE_VENDOR_CACHE` を設定したままにしてください。設定しない場合、Composeは空のキャッシュコンテキストを使用し、通常通りダウンロードを行います。プロジェクト名と `flinteye-data` ボリュームは変更されません。リカバリ中に `down -v` を使用しないでください。


## 1.2.0 development: Docker Desktop

1.2.0で再ビルドされたイメージを使用する場合は、チェックアウトから`docker compose -f deploy/compose.desktop.yaml up -d`を使用してください。配布後は、同じリリースの`compose.desktop.yaml`とその正確なイメージタグを使用してください。この個別のブリッジ設定では、HTTP TCP 18080およびWebRTC UDP 8189がホストのループバックに対してのみ公開されます。コンテナはHTTPリスナーを自身のインターフェースにバインドし、ホストループバックのICE候補をアドバタイズします。ホストのブラウザで http://127.0.0.1:18080 を開いてください。USB転送およびONVIFマルチキャスト検出は含まれていないため、アクセス可能なIPカメラを手動で設定してください。これはLANサーバー設定ではありません。既存のルートComposeは、Linuxホストネットワーキングとそのボリュームを維持します。更新時にプロジェクト名を変更したり、ボリュームを消去したりしないでください。どちらのルートも、停止時の通常の録画終了処理に60秒を要します。終了コード143のみを完了の証拠とするのではなく、停止の受付を確認し、最後の録画をデコードして確認してください。[LANサーバーのセットアップ](LAN_ACCESS.ja.md) · [必要な承認](DEVELOPMENT_1_2_0.ja.md)
