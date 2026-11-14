<a id="docker-compose"></a>
# Docker Compose

[English](DOCKER.md)

[Documentation](README.ja.md) · [GHCR publication setup](RELEASING.ja.md#ghcr-setup)

Docker Engine と Compose プラグインがインストールされた Linux サーバー上でこの手順を使用します。
イメージは `linux/amd64` および `linux/arm64` をターゲットにしています。Windows/macOS では、ネイティブのデスクトップパッケージを使用することが推奨される方法です。
ホストネットワークを使用することで、ONVIF の検出と WebRTC が維持されます。Docker Desktop の USB フォワーディングは含まれていません。

<a id="install-without-cloning"></a>
## クローンせずにインストールする

**UNDER DEVELOPMENT.** 公開 GHCR イメージはまだ利用できません。最初に予定されているイメージは `ghcr.io/noguhiro2002/flinteye:1.1.2-preview.1` です。それまでの間は[ローカル開発ビルド](#build-the-development-image)を使用してください。以下のプル手順は公開後にのみ適用されます。

公開されたパブリックイメージは、GitHub アカウントやトークンなしでプルできます。Docker に期限切れの保存済み認証情報がある場合は、匿名でプルする前に `docker logout ghcr.io` を実行してください。メンテナーによるプライベートテストでは引き続き、承認されたアカウントと `read:packages` 権限を持つクラシックトークンが必要となり、`docker login ghcr.io -u YOUR_GITHUB_USERNAME` のパスワードプロンプトで入力します。トークンを `.env` やコマンド引数に入れないでください。

同じバージョンの GitHub Release から `compose.yaml` をダウンロードし、新しいディレクトリに配置して、`.env` を作成します。

```dotenv
FLINTEYE_IMAGE=ghcr.io/noguhiro2002/flinteye:1.1.2-preview.1
```

プレビュー版には `latest` イメージタグはありません。上記のようにテスト済みの正確なバージョンを固定してください。公開には自動テストと実機テストが必要です。現時点ではパブリックイメージの存在は保証されていません。

該当のディレクトリから以下を実行します。

```sh
docker compose pull
docker compose up -d
docker compose exec flinteye cat /data/setup-token
```

http://127.0.0.1:18080 を開き、使い捨てトークンを入力して管理者パスワードを作成します。
リモートサーバーの場合は、最初に SSH トンネルを作成します。

```sh
ssh -L 18080:127.0.0.1:18080 your-server
```

セットアップトークンを issue に投稿したり、パスワードをコマンド引数に入れたりしないでください。
他の LAN ユーザー向けには、[HTTPS リバースプロキシ](DISTRIBUTION.ja.md#user-installation)を設定してください。
HTTP/API/MediaMTX リスナーはループバック上に維持されます。WebRTC には UDP 8189 も必要です。

<a id="storage-and-cameras"></a>
## ストレージとカメラ

名前付きボリューム `flinteye-data` により、コンテナの再作成をまたいで設定、インベントリ、録画が保持されます。
プロセスは UID/GID 10001 を使用します。バインドマウントされたフォルダは、その識別子で書き込み可能である必要があります。
Web UI で選択したパスは、コンテナ内のパスを指します。追加の録画ディスクは明示的にマウントしてください。

IP カメラにはネットワークアクセスが必要です。オプショナルの USB マッピングは `compose.yaml` に示されています。ホストの実際のデバイスとビデオグループの GID を選択してください。
オプショナルのネイティブ Raspberry Pi CSI ヘルパーはバンドルされていません。ARM64 ビルドでは USB/IP 入力が機能します。

<a id="update-and-rollback"></a>
## 更新とロールバック

リリースノートを確認し、最初に設定とインベントリのバックアップを作成してください。`.env` 内の固定バージョンを変更してから、以下を実行します。

```sh
docker compose pull
docker compose up -d
docker compose logs --tail=50 flinteye
```

コンテナの置き換えにより、監視が一時的に中断されます。アップデートが自動的に適用されることはありません。
ロールバックするには、`.env` に以前の正確な `ghcr.io/noguhiro2002/flinteye:VERSION` を戻し、`docker compose pull` と `docker compose up -d` を実行します。リリースで必要な場合は、対応する設定のバックアップを復元します。アップグレードが検証されるまで、古いバージョンとその設定バックアップを保持してください。

`docker compose down` はボリュームを保持したままコンテナを停止・削除します。
保存されたデータを明示的に消去する意図がない限り、`-v` を追加しないでください。

<a id="build-the-development-image"></a>
## 開発イメージのビルド

リポジトリのチェックアウトから以下を実行します。

```sh
docker compose -f deploy/compose.dev.yaml up -d --build
docker compose -f deploy/compose.dev.yaml exec flinteye cat /data/setup-token
```

これにより、ローカルの `flinteye:development` イメージが作成されますが、公開はされません。
同じポート上で開発インスタンスとインストール済みインスタンスを同時に実行しないでください。

<a id="if-the-mediamtx-download-times-out"></a>
### MediaMTX のダウンロードがタイムアウトする場合

`packaging/vendor.py` からの `TLS handshake operation timed out` エラーは、ビルドがアップロードファイルをダウンロードできなかったことを意味します。これはコンパイラの erros ではなく、ネットワーク/ダウンロードの失敗です。ダウンロードは一時的な失敗に対して最大 3 回までリトライされ、検証済みファイルが再利用されます。SHA-256 および TLS 証明書のチェックは有効なままです。また、Go のモジュール/ビルドキャッシュにより、繰り返しの作業が削減されます。

ホスト上で MediaMTX ダウンロードキャッシュを準備するには、Python 3.11 以降および最新の Docker Compose プラグイン（[2.17.0 以降](https://docs.docker.com/reference/compose-file/build/#additional_contexts)）を使用し、チェックアウトのルートから以下のコマンドを実行します。

```sh
python3 packaging/vendor.py media-cache
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

信頼できる FlintEye ビルドから対応する MediaMTX ソースアーカイブをすでに持っている場合は、再度ダウンロードする代わりにその固定ファイルをインポートしてください。`MEDIA_SOURCE_ARCHIVE` を実際のアーカイブパスに置き換えてください。

```sh
python3 packaging/vendor.py media-cache --from-source-archive MEDIA_SOURCE_ARCHIVE
export FLINTEYE_VENDOR_CACHE="$(pwd)/vendor/downloads"
docker compose -f deploy/compose.dev.yaml up -d --build
```

インポーターは、選択された 3つのファイルを再利用する前に、固定された MediaMTX/HLS チェックサムと照合して検証します。任意のアーカイブパスを抽出するわけではありません。ソースのダウンロードは、どちらの CPU アーキテクチャでも機能します。別のバージョンのソースアーカイブは、そのチェックサムが現在のチェックアウトと一致する場合にのみ使用できます。

これによりバイパスされるのは、MediaMTX ソース、HLS バンドル、およびライセンスのダウンロードのみです。ベースイメージ、システムパッケージ、Go モジュール、Python パッケージ、およびフロントエンドの依存関係には引き続きネットワークアクセスが必要です。それらが失敗した場合は、検証を無効にするのではなく、Docker デーモン/ビルドのネットワークおよびプロキシ設定を確認してください。

このキャッシュを使用して再ビルドする場合は、`FLINTEYE_VENDOR_CACHE` を設定したままにしてください。これがない場合、Compose は空のキャッシュコンテキストを使用し、通常通りダウンロードを行います。プロジェクト名と `flinteye-data` ボリュームは変更されません。リカバリ中に `down -v` を使用しないでください。
