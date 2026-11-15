<a id="docker-compose"></a>
# Docker Compose

[English](DOCKER.md)

[Documentation](README.ja.md) · [GHCR公開設定](RELEASING.ja.md#ghcr-setup)

Docker EngineおよびComposeプラグインがインストールされたLinuxサーバー上で、この手順を使用します。
イメージは `linux/amd64` および `linux/arm64` をターゲットとしています。Windows/macOSでは、ネイティブのデスクトップパッケージが推奨ルートとなります。
ホストネットワークにより、ONVIFディスカバリーとWebRTCが維持されます。Docker DesktopのUSB転送は含まれていません。

<a id="install-without-cloning"></a>
## クローンせずにインストールする

**UNDER DEVELOPMENT。** 公開GHCRイメージはまだ利用できません。最初に計画されているイメージは `ghcr.io/noguhiro2002/flinteye:1.1.3-preview.1` です。その間は[ローカル開発ビルド](#build-the-development-image)を使用してください。以下のpull手順は、公開後にのみ適用されます。

公開されたパブリックイメージは、GitHubのアカウントやトークンなしでpullできます。Dockerに期限切れの保存済み認証情報がある場合は、匿名でpullする前に `docker logout ghcr.io` を使用してください。プライベートなメンテナーテストでは引き続き、承認済みのアカウントと `read:packages` を持つクラシックトークンが必要であり、これらは `docker login ghcr.io -u YOUR_GITHUB_USERNAME` のパスワードプロンプトに入力します。`.env` やコマンド引数にトークンを決して入れないでください。

同じバージョンのGitHub Releaseから `compose.yaml` をダウンロードし、新しいディレクトリに配置して、`.env` を作成します：

```dotenv
FLINTEYE_IMAGE=ghcr.io/noguhiro2002/flinteye:1.1.3-preview.1
```

プレビュー版には `latest` イメージタグがありません。上記のようにテスト済みの正確なバージョンを指定してください。公開には自動テストと実機でのチェックが必要です。現時点ではパブリックイメージの存在は保証されていません。

そのディレクトリから実行します：

```sh
docker compose pull
docker compose up -d
docker compose exec flinteye cat /data/setup-token
```

http://127.0.0.1:18080 を開き、1回限りのトークンを入力して管理者パスワードを作成します。
リモートサーバーの場合は、最初にSSHトンネルを作成します：

```sh
ssh -L 18080:127.0.0.1:18080 your-server
```

セットアップトークンをIssueに投稿したり、コマンド引数にパスワードを入れたりしないでください。
他のLANユーザーのために、[HTTPSリバースプロキシ](DISTRIBUTION.ja.md#user-installation)を設定してください。
HTTP/API/MediaMTXリスナーはループバック上に留まります。WebRTCにはUDP 8189も必要です。

<a id="storage-and-cameras"></a>
## ストレージとカメラ

名前付きボリューム `flinteye-data` により、コンテナの置き換え後も設定、インベントリ、録画が保持されます。
このプロセスはUID/GID 10001を使用します。バインドマウントされたフォルダは、そのIDで書き込み可能である必要があります。
Web UIで選択したパスは、コンテナ内のパスを指します。追加の録画用ディスクは明示的にマウントしてください。

IPカメラにはネットワークアクセスが必要です。オプションのUSBマッピングは `compose.yaml` に示されています。ホストの実際のデバイスとビデオグループのGIDを選択してください。
オプションのネイティブRaspberry Pi CSIヘルパーはバンドルされていません。ARM64ビルドではUSB/IP入力が機能します。

<a id="update-and-rollback"></a>
## 更新とロールバック

リリースノートを確認し、最初に設定とインベントリのバックアップを取ります。`.env` で指定したバージョンを変更し、以下を実行します：

```sh
docker compose pull
docker compose up -d
docker compose logs --tail=50 flinteye
```

コンテナの置き換えにより、監視が一時的に中断されます。アップデートが自動的に適用されることはありません。
ロールバックするには、前の正確な `ghcr.io/noguhiro2002/flinteye:VERSION` を `.env` に戻し、`docker compose pull` と `docker compose up -d` を実行します。リリースで必要な場合は、一致する設定のバックアップを復元します。アップグレードが検証されるまで、古いバージョンとその設定バックアップを保持してください。

`docker compose down` は、ボリュームを保持したままコンテナを停止・削除します。
保存されたデータを明示的に消去する意図がない限り、`-v` を追加しないでください。

<a id="build-the-development-image"></a>
## 開発イメージのビルド

リポジトリのチェックアウトから：

```sh
docker compose -f deploy/compose.dev.yaml up -d --build
docker compose -f deploy/compose.dev.yaml exec flinteye cat /data/setup-token
```

これによりローカルの `flinteye:development` イメージが作成されますが、公開はされません。
同じポート上で開発インスタンスとインストール済みインスタンスを同時に実行しないでください。

<a id="if-the-mediamtx-download-times-out"></a>
### MediaMTXのダウンロードがタイムアウトする場合

`packaging/vendor.py` からの `TLS handshake operation timed out` エラーは、ビルドが上流のファイルをダウンロードできなかったことを意味します。これはコンパイラのエラーではなく、ネットワーク/ダウンロードの失敗です。ダウンロードでは一時的な障害に対して最大3回まで再試行が行われ、検証済みのファイルが再利用されます。SHA-256およびTLS証明書のチェックは有効なままです。Goのモジュール/ビルドキャッシュも重複する作業を削減します。

ホスト上でMediaMTXダウンロードキャッシュを準備するには、Python 3.11以降と最新のDocker Composeプラグイン（[2.17.0以降](https://docs.docker.com/reference/compose-file/build/#additional_contexts)）を使用し、チェックアウトのルートから次のコマンドを実行します：

```sh
python3 packaging/vendor.py media-cache
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

信頼できるFlintEyeのビルドから対応するMediaMTXソースアーカイブをすでに持っている場合は、再度ダウンロードする代わりにその指定ファイルをインポートしてください。`MEDIA_SOURCE_ARCHIVE` を実際のアーカイブパスに置き換えてください：

```sh
python3 packaging/vendor.py media-cache --from-source-archive MEDIA_SOURCE_ARCHIVE
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

インポーターは、選択された3つのファイルを再利用する前に、指定されたMediaMTX/HLSチェックサムと照合して検証します。任意のアーカイブパスを抽出することはありません。ソースのダウンロードはどちらのCPUアーキテクチャでも機能します。別のバージョンのソースアーカイブは、そのチェックサムが現在のチェックアウトと一致する場合にのみ使用できます。

これによりバイパスされるのは、MediaMTXソース、HLSバンドル、およびライセンスのダウンロードのみです。ベースイメージ、システムパッケージ、Goモジュール、Pythonパッケージ、およびフロントエンドの依存関係には引き続きネットワークアクセスが必要です。それらが失敗した場合は、検証を無効にするのではなく、Dockerデーモン/ビルドネットワークおよびプロキシの設定を確認してください。

このキャッシュで再ビルドする場合は、`FLINTEYE_VENDOR_CACHE` を設定したままにしてください。設定しない場合、Composeは空のキャッシュコンテキストを使用し、通常どおりダウンロードを行います。プロジェクト名と `flinteye-data` ボリュームは変更されません。リカバリ中に `down -v` を使用しないでください。
