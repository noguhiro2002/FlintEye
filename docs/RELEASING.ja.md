<a id="build-and-release-flinteye"></a>
# FlintEye のビルドとリリース

[English](RELEASING.md)

[Documentation](README.ja.md) · [Acceptance checklist](ACCEPTANCE.ja.md)

<a id="source-first-public-development"></a>
## ソースファーストの公開開発

公開履歴は単一の **1.1.1 source snapshot** から始まります。次のビルドはアプリケーション **1.1.2**、ディストリビューション **`v1.1.2-preview.1`** です。古いプライベートインストーラーやエミュレートされたローカルビルドは、パブリックリリースとして再公開されません。既存のプライベートチェックアウトは新しいディレクトリに再度クローンする必要があります。無関係な古い履歴をこのリポジトリにマージしないでください。

通常のプッシュでは **Distribution checks** が実行されます。**Build release** は手動で行われ、デスクトップインストーラーやテスト済みコンテナアーカイブを含む Actions アーティファクトを作成します。パブリックリポジトリでは、これらのアーティファクトとログはリポジトリの閲覧者がアクセス可能であり（アーティファクトのダウンロードには GitHub へのサインインが必要）、これらは承認されたリリースではなく開発ビルドの結果です。カメラの認証情報、録画、個人プロフィールを CI の入力やログに含めないでください。

**Publish tested release** は次のチャネルをサポートしています：

| Requirement | `private-test` | `public-preview` | `stable` |
| --- | --- | --- | --- |
| Repository | Private | Public | Public |
| Successful complete manual build, same default-branch commit | Required | Required | Required |
| Repository variable | None | `PUBLIC_PREVIEW_ENABLED=true` | `PUBLIC_RELEASE_ENABLED=true` |
| Device acceptance and license/source review | May be pending | Required | Required |
| Embedded channel | Internal test | `preview` | `stable` |
| GitHub release | Normal testing release | **Pre-release**, not Latest | Normal release, Latest |
| Image tags | Exact preview only | Exact preview only | Version and `latest` |
| Command installers | Excluded | Included, pinned preview | Included, pinned stable version |

両方のパブリックフラグは `false` として始まります。まだ行われていないチェックを確認しないでください。パブリックプレビューの受け入れには、Windows x64、M1 Mac、Linux x64 が必要です（カメラキャプチャ、録画/再生、GUI 終了による所有プロセスの停止、バンドルされたプログラムを削除しつつデータを保持する Windows アンインストール）。その他のハードウェアの組み合わせは保留中として記録してください。[acceptance checks](ACCEPTANCE.ja.md) を参照してください。

<a id="ghcr-setup"></a>
## GHCR のセットアップ

イメージは `ghcr.io/noguhiro2002/flinteye` を使用します。ディストリビュージョブのみが `packages: write` を受け取り、`GITHUB_TOKEN` を使用します。Docker Hub の認証情報や個人用の公開トークンは不要です。OCI のソース/ドキュメントラベルにより、パッケージがこのリポジトリに関連付けられます。

GitHub は初期状態でパッケージをプライベートとして作成します。リポジトリの可視性とパッケージの可視性は別個のものです。そのため、公開は次の 2 つの明示的なフェーズに分割されます：

1. **prepare:** 再ビルドなしでテスト済みイメージアーカイブをアップロードし、ドラフトリリースを作成します。チェックサム、ソースコミット、アーキテクチャ、イメージダイジェストを確認します。この段階では、最初の GHCR パッケージはまだプライベートである可能性があります。
2. パッケージの設定でリポジトリの関連付けを確認し、対象のパブリックパッケージを **Public**に変更します。これにより検証済みコンテナが公開されるため、準備フェーズの前にもデバイス/ライセンスの受け入れが必要です。プライベートテスト用のパッケージはプライベートのままにしてください。
3. **publish:** 同じビルド実行 ID、ソースコミット、チャネル、プレビュー番号で再実行します。アップロードされたアセットとコンテナのレシートを再確認し、ドラフトを公開します。このフェーズでは、パブリックチャネル向けのプライベートパッケージは拒否され、アーティファクトの再ビルドや置き換えは一切行われません。

ワークフローは可視性を自動的には変更しません。パブリックイメージでは匿名プルが許可されます。プライベートテストには認証された `read:packages` の認証情報が必要です。標準の GitHub ホステッドランナーが使用され、より大型の有料ランナーは設定されていません。ビルド前に現在のストレージ制限とランナーの可用性を確認してください。

公式リファレンス: [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)。

<a id="version-and-source-of-truth"></a>
## バージョンと真実のソース (Source of Truth)

`flinteye_app/_version.py`には、`VERSION`（数値の `X.Y.Z`）、`RELEASE_VERSION`（例：`1.1.2-preview.1`）、`RELEASE_CHANNEL`（`source`、`preview`、または `stable`）が保持されます。インストーラーのファイル名、Inno Setup、DEB/RPM メタデータには数値バージョンを使用し、ダウンロード URL、アップデート比較、イメージタグには完全なリリースバージョンを使用します。これらの値はテスト済みビルドマニフェストと一致している必要があります。ソーススナップショットには `source` チャネルを使用し、インストーラーのアップデートは通知しません。
既存のリリースやイメージバージョンを上書きしないでください。

`packaging/vendor-lock.json` はソース URL と SHA-256 ハッシュを固定します。
FFmpeg、x264、FreeType、HarfBuzz、MediaMTX はこれらの検証済みソースからビルドされます。
MediaMTX のビルドでは、プレコンパイルされた Raspberry Pi CSI ヘルパーが除外されています。FlintEye の USB/IP 入力は引き続き利用可能です。
埋め込み HLS アセットは、ピン留めされたアップストリームソースのハッシュに対して検証されます。
Go モジュールはアップストリームの go.sum を使用し、保持されたソースツリーにベンダー管理されます。

Python の依存関係セットは `packaging/constraints.txt` で制約されています。npm はパッケージロックを使用します。
依存関係を意図的に更新し、テストと新しいリリースビルドを実行してください。

<a id="build-and-test"></a>
## ビルドとテスト

1. 新しいリリースを準備する際に 3 つのバージョン/チャネルフィールドすべてを更新し、変更をコミットします。
2. デフォルトブランチから **Distribution checks** を実行し、次に **Build release** を実行します。
3. **release-bundle** をダウンロードし、[acceptance checks](ACCEPTANCE.ja.md) を実行します。
4. ビルド実行 ID とコミット SHA を保持します。公開にはそれらのアーカイブされたアーティファクトが使用され、再ビルドは行われません。

ネイティブマトリックスビルドでは、対応するランナー上で Windows x64/ARM64 および macOS Intel/ARM64 をビルドします。Windows では、アクティブな API を使用して実際の EXE インストーラーとアンストーラーを実行し、シャットダウン、バンドルファイルの削除、デフォルトデータの保持を検証します。この自動チェックは物理カメラの受け入れに代わるものではありません。
Windows と macOS では Python 3.14.10 を使用します。これには両方の CPU 向けのインストーラービルドがあります。
Linux パッケージは、Ubuntu、Enterprise Linux、64 ビット Raspberry Pi OS 用に更新された Rocky Linux 9 の内部でビルドされます。バンドルされたランタイムには GLIBC_2.35 シンボルが必要です。DEB では libc6 2.35 以降が必要であり、RPM では libc.so.6(GLIBC_2.35)(64bit) 機能が必要となるため、必要に応じて dnf が古い Rocky 9 インストールをバックポートされたランタイムにアップグレードします。
Linux ビルダーおよびサーバーイメージでは、ピン留めされた Python 3.13 ランタイムを使用します。
GitHub ランナーの可用性と最小 OS ハードウェアチェックは個別の懸念事項であり、新しいランナー古い OS が動作することを証明するものではありません。

完全なリリースバンドルの場合は、**desktop_only** のチェックを外したままにしてください。Windows/macOS のパッケージングを診断する場合にのみ選択してください。その実行では個別のデスクトップアーティファクトが生成され、公開には使用できません。

ソースビルドには、特に初回実行時に相当な時間がかかる場合があります。ビルドアーティファクトは 30 日間保持されます。
お使いの GitHub プランでランナーを利用できない場合は、ご自身のマシンで同等のネイティブビルドを実行し、完全なリリースマトリックスを主張する前にランナーの可用性を解決してください。

<a id="local-native-build"></a>
### ローカルネイティブビルド

M1 / Apple Silicon Mac の場合は、[local DMG guide](LOCAL_MACOS_BUILD.ja.md) を使用してください。これにより、分離されたビルドの準備、共有 Settings インターフェイスの再ビルド、GitHub Actions なしでのインストール済み DMG および MediaMTX パスリカバリのテストが行われます。これによりローカルテストアーティファクトが生成されますが、公開はされません。

Windows/macOS では、Python 3.14.10、Node.js 22.12+、Go 1.27、C/C++ コンパイラ、make、CMake、Ninja、pkg-config、Meson、NASM（x64）をインストールします。
Windows では MSYS2 UCRT64 または CLANGARM64 を使用します。macOS は `MACOSX_DEPLOYMENT_TARGET=14.0` でビルドします。
ネイティブ Linux パッケージの場合は、以下の Docker ビルダーを使用してください。ピン留めされた Python 3.13.18 ソースをコンパイルします。

```sh
python -m pip install -c packaging/constraints.txt -r requirements.txt -r packaging/requirements-build.txt meson==1.9.1 ninja==1.13.0
bash packaging/build_vendor.sh
python packaging/build_bundle.py --vendor vendor
python packaging/smoke_desktop_bundle.py
```

`/DAppVersion=X.Y.Z /DAppArch=amd64`（または `arm64`）を使用して Inno Setup で Windows インストーラーをコンパイルします。
macOS バンドルビルダーは、Applications ショートカットを含む DMG を作成します。

Linux の場合は、ターゲット CPU 上でパッケージセット全体をビルドします：

```sh
docker buildx build -f packaging/LinuxBuilder.Dockerfile --target artifacts --output type=local,dest=dist .
```

<a id="redistribution-material"></a>
### 再配布資料

すべてのネイティブターゲットには、対応するソースとライセンス ZIP が含まれています。
Linux パッケージには、署名入りの正確なバージョンの Rocky ソース RPM と、LGPL ライブラリを含むバンドルにコピーされたシステムライブラリの通知も保持されます。デスクトップバンドルには、使用されていないインタラクティブな `readline` モジュールは含まれません。
Docker ビルドは、FFmpeg/FFprobe 依存関係クロージャの正確なソースバージョンをキャプチャし、Debian ソースパッケージとしてエクスポートします。
MediaMTX の変更されたソースツリーとベンダー管理された依存関係は個別にエクスポートされます。
必要な対応ソースをアップストリームのホームページリンクに置き換えないでください。

配布前に、Python インタープリター、Tcl/Tk、OS ライブラリ、およびその他のバイナリ依存関係について、生成されたインベントリを確認してください。
古いリリースについても、ソース/ライセンスアーカイブをダウンロード可能な状態に維持してください。FFmpeg `--enable-nonfree` を有効にするビルドは失敗します。

<a id="source-cache-option"></a>
### ソースキャッシュオプション

Docker は、すでにダウンロードされたパブリックな MediaMTX/HLS アーカイブのみを含む BuildKit 名前付きコンテキスト `vendor-downloads` を使用できます。
ビルドは引き続きピン留めされたハッシュを検証します。これにより、Docker 内での直接のソースダウンロードが利用できない環境でのテストが可能になります：

```sh
docker build --build-context vendor-downloads=/path/to/verified-public-source-cache -t flinteye:development .
```

そのキャッシュに認証情報、ランタイム設定、録画を入れないでください。

<a id="publish-the-tested-build"></a>
## テスト済みビルドの公開

成功した完全なビルドの正確なデフォルトブランチコミットで **Publish tested release** を実行します。`public-preview`、プレビュー番号 `1`、および前述の 2 つのフェーズを選択します。ビルド実行 ID は変更しないでください。パブリック受け入れチェックボックスと一致するリポジトリ有効化フラグの両方が true である必要があります。安定版の公開には、さらに新しい安定版アイデンティティと完全なビルドが必要であり、プレビューのインプレースリネームではありません。

ワークフローは、アーカイブされたすべてのファイルを検証し、テスト済みの amd64/arm64 コンテナアーカイブをロードし、CPU とソースのアイデンティティをチェックし、マルチプラットフォームマニフェストを作成し、レジストリダイジェストを記録します。リリースアセットには、インストーラー、対応するソース/ライセンス、バイリンガルガイド/ノート、Compose、元のビルド情報、ディストリビューションメタデータ、チェックサム、および（パブリックチャネルの場合は）ピン留めされたコマンドインストーラーが含まれます。

既存のタグ、インストーラーの内容、バージョン管理されたイメージタグが上書きされることはありません。失敗した準備操作により、アップロードされたイメージやドラフトが残る可能性があります。リカバリ前にその来歴を検査して保持してください。同じビルドに対して正常に準備されたドラフトは、2番目のフェーズによって公開できます。安定版の公開のみがコンテナ `latest` タグを更新します。

<a id="user-updates"></a>
## ユーザーアップデート

プレビューデスクトップビルドは、フルバージョンを使用して公開されたプレビューと安定版リリースをチェックします。安定版ビルドはプレビューを無視します。アップデートリンクは正確なタグを指します。ソーススナップショットは Git からアップデートされます。ユーザーはモニタリングを停止した後に手動でインストールします。
Docker 管理者はイメージバージョンを変更し、`docker compose pull` の実行後に `docker compose up -d` を実行します。
以前のリリースのアーティファクトを保持し、設定の移行/ロールバック要件を文書化してください。
