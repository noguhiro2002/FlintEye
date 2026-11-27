<a id="build-a-test-dmg-on-your-m1-mac"></a>
# M1 Mac でテスト用 DMG をビルドする

[English](LOCAL_MACOS_BUILD.md) · [Documentation](README.ja.md) · [Build and release](RELEASING.ja.md)

この手順は、GitHub Actions のビルド時間を消費せずに、Apple Silicon Mac 上で現在コミットされているソースをビルドします。これには、MediaMTX のパス修正、統合された Settings 画面、および **FlintEye API** のドキュメントタイトルが含まれます。FFmpeg、FFprobe、MediaMTX は自動的にビルドおよびバンドルされます。FlintEye 用に別途コピーをインストールする必要はありません。

結果はローカルのテストビルドになります。アップロード、公開、「アプリケーション」フォルダーへのインストール、既存の FlintEye データの変更などは一切行われません。既存の GitHub インストーラーは変更されません。この手順はご自身の Mac を対象としており、サポートされているすべての macOS バージョンとの互換性を確立するものではありません。

<a id="1-prepare-the-mac-once"></a>

Preview 10 の現在のソースは `main` からビルドします。ビルド時に表示されるコミットを記録し、テスト専用のプロファイルを使ってください。

## 1. Mac の事前準備を 1 回行う

Mac 本体でターミナルを使用し、**Rosetta を使用して開く**が無効になっている状態にします。電源を接続し、ソースアーカイブ、メディアコンパイル、Python パッケージ、DMG に十分な空き容量を確保してください。初期段階でおおよそ 15〜20 GB の作業スペースが必要です。ビルド時間は Mac とネットワーク環境に依存するため、初回実行時は時間がかかることがあります。

Apple のコマンドライン開発者ツールをインストールし、インストールが完了するのを待ちます：

```sh
xcode-select --install
```

すでにインストールされている場合は続行します。`/opt/homebrew/bin/brew` が存在しない場合は、[公式の手順](https://docs.brew.sh/Installation)に従ってネイティブの Apple Silicon 版 Homebrew をインストールします。その後、ビルドツールをインストールします：

```sh
/opt/homebrew/bin/brew install python@3.14 python-tk@3.14 node@22 go cmake pkgconf ninja gh
```

Python 3.14.10以降の3.14パッチバージョン、Node.js 22.12以降の22.x、およびGo 1.27以降を使用してください。このスクリプトは、シェルでConda環境がアクティブであっても、明示的にネイティブのHomebrewツールを選択し、独自のPython環境を作成します。Homebrewは [Python 3.14用のTk](https://formulae.brew.sh/formula/python-tk@3.14) を個別に提供しています。Tkは、セットアップや接続情報、フォルダー選択ウィンドウに必要です。初期管理者パスワードはブラウザーで入力します。[Node.js 22](https://formulae.brew.sh/formula/node@22) は既存のビルドワークフローと一致しており、固定されたMediaMTXソースには [Go 1.27以降](https://formulae.brew.sh/formula/go) が必要です。

<a id="2-get-the-updated-source"></a>
## 2. 更新されたソースを取得する

パブリックソース専用のチェックアウトを作成します。GitHub へのログインは不要です。スペースを含まないパスを選択してください。以前のプライベートリポジトリを使用していた場合は、関連のない履歴をプルするのではなく、新しいディレクトリにクローンしてください。

```sh
mkdir -p ~/Developer
cd ~/Developer
git clone --branch main https://github.com/noguhiro2002/FlintEye.git FlintEye-build
cd FlintEye-build
```

以降のビルドでは、再度クローンするのではなく、そのチェックアウトを更新してください：

```sh
cd ~/Developer/FlintEye-build
git switch main
git pull --ff-only
```

このチェックアウトはクリーンな状態に保ってください。ヘルパーは現在のコミットの新しいスナップショットをビルドするため、コミットされていないソースの変更がある場合は停止します。無視された録画、ランタイム設定、古いビルドディレクトリ、依存関係フォルダーはスナップショットにコピーされません。

<a id="3-build-and-automatically-verify-the-dmg"></a>
## 3. DMG のビルドと自動検証

メニューバーのアイコンから **Quit FlintEye** を使用して、実行中の FlintEye をすべて終了します。また、ポート 8554、8889、9997、または UDP 8189 を使用している個別の MediaMTX インスタンスも停止してください。ブラウザを閉じるだけではモニタリングは停止しません。

最初にツールを確認します：

```sh
/opt/homebrew/opt/python@3.14/bin/python3.14 packaging/build_macos_local.py --check-only
```

次にビルドを実行します。`caffeinate` はこのコマンドの実行中に Mac がスリープ状態になるのを防ぎます。蓋を開けたままにしておいてください：

```sh
caffeinate -i /opt/homebrew/opt/python@3.14/bin/python3.14 packaging/build_macos_local.py
```

ヘルパーは M1 MacBook Air の場合、デフォルトで 2 つのコンパイルジョブを使用します。メモリが不足している場合は、`--jobs 1` を指定して再実行してください。試行ごとに `dist/local-macos/` 配下に独自のディレクトリが割り当てられるため、再試行しても以前のビルドが上書きされることはありません。

順番に以下の手順を実行します：

1. コミットされたソースを新しいビルドディレクトリに展開し、制約された Python 依存関係を別の環境にインストールします。
2. MediaMTX の起動リグレッションテストを実行し、ピン留めされたメディアツールをコンパイルし、認証されたメディア入力をテストします。
3. 共有 Web インターフェイスを再ビルドし、Python およびメディアツールとともに ARM64 アプリケーションおよび DMG にパッケージ化します。通常のビルドと同様のローカルアドホック署名を適用します。Apple デベロッパーアカウントは不要です。
4. DMG をマウントし、`codesign --verify --deep --strict` で最終アプリを検証し、内部リンクを保持したままアプリをコピーし、DMG を取り出します。コピーしたアプリを検証し、意図的に改ざんされたコピーが復元前に検証に失敗することを証明します。Gatekeeper の評価を個別に記録します。アドホック署名は Developer ID の信頼や公証を意味するものではありません。その後、セットアップとメディアをテストします。セットアップ、認証、ワーカーの読み込み、MediaMTX、合成録画、再生のダウンロードを確認します。
5. そのテストアプリを別のディレクトリに移動し、同じ一時プロファイルで再起動します。これにより、macOS の起動失敗に対処する保存済みパスの修復機能を確認します。

自動テストでは、一時アカウントと生成されたビデオを使用します。カメラを開いたり、保存されたパスワードを使用したり、既存の録画を変更したりすることはありません。

成功すると、**Local DMG verified:** と正確なファイルパスが表示されます。そのビルドディレクトリの下にある `artifacts` フォルダーを開きます。これには以下が含まれます：

- `FlintEye-VERSION-local-<commit>-macos-arm64.dmg`
- 対応するメディアソースとライセンス
- `vendor-sha256.json`、`build-info.json`、`-signature.json` の整合性/Gatekeeper レポート、および `SHA256SUMS`

アプリケーションは選択されたソースからの数値バージョンを報告します。ファイル名とビルド情報は、新しいソースコミットを識別します。これは既存リリースの置き換えではありません。ファイルの整合性を確認するには、`artifacts` フォルダーでターミナルを開き、次を実行します：

```sh
shasum -a 256 -c SHA256SUMS
```

ステップが失敗した場合、ヘルパーは停止し、作業ディレクトリを表示します。障害を報告する際はその `build.log` を保持してください。失敗したテスト後に `source/dist` の中に残された DMG は、検証された結果ではありません。ヘルパーを再実行すると、新規のビルドが開始されます。ソースのダウンロードでは、HTTPS 証明書とチェックサムの検証が維持されます。

<a id="4-install-and-check-your-existing-setup"></a>
## 4. 既存のセットアップをインストールして確認する

1. 古い FlintEye が停止していることを確認します。新しく検証された DMG を開き、`/Applications/FlintEye.app` を完全なアプリで置き換え、DMG を取り出します。インストールしたアプリを開きます。`~/Library/Application Support/FlintEye` を削除しないでください。
2. 既存の管理者パスワードでサインインします。カメラと録画設定が保持されていることを確認します。macOS から確認を求められた場合は、[インストールガイド](INSTALL.ja.md)に記載されているアプリ固有の**「プライバシーとセキュリティ」→「このまま開く」**操作を使用してください。
3. MediaMTX が起動し、**Live View** に映像が表示されることを確認します。古い保存済み `AppTranslocation` 実行ファイルのパスは自動的に修復されるはずです。カメラがオンとオフを繰り返さなくなったことを確認してから、短いクリップを録画および再生します。
4. **Settings** を開きます。個別の**「録画ストレージとビューアーのアクセス」**パネルがなくなっているはずです。フォルダー・容量・保持期間は **Basic → Recording**、閲覧者のパスワードは **Basic → Runtime & access**、更新確認は **Information** から設定します。録画の変更を保存するには**「変更を保存」**を使用します。タイトルが **FlintEye API** になっていることを `/docs` と `/redoc` で確認します。
5. アプリを終了して再度開き、ログイン時の自動起動を個別に確認します。これらの物理カメラおよびデスクトップの確認は、自動ビルド結果とは区別して行ってください。

それでも映像が表示されない場合は、`~/Library/Application Support/FlintEye/logs/` 配下の `orchestrator.log` および `mediamtx.log` を確認してください。起動パスが修正されても、カメラの権限、ポートの競合、キャプチャフォーマットの問題が解決されたとは限りません。

別のプロファイルで試す場合は、起動中の FlintEye を終了し、macOS でテスト用アプリの起動を許可します。許可操作でアプリが開いたら、もう一度終了してください。インストール先に合わせて、次のアプリのパスを変えます。

```bash
profile=$(mktemp -d "${TMPDIR:-/tmp}/flinteye-macos-qa.XXXXXX")
open -n "$HOME/Applications/FlintEye.app" --args --data-dir "$profile" --port 18180 --disable-lan
```

新しいフォルダーに `runtime.json` ができたことを確認し、`http://127.0.0.1:18180` を開きます。録画停止の確認では、録画中に **Stop monitoring** を押します。次にもう一度録画を始め、録画をオフにして保存してから **Stop monitoring** を押します。両方の映像を再生でき、Quit で API とメディアプロセスが終了することを確認してください。

<a id="the-same-settings-design-on-other-installations"></a>
## 他のインストール環境における同じ Settings のデザイン

Windows、macOS、Linux パッケージ、Docker、およびソースからのインストールでは、すべて同じ `frontend/src` インターフェイスが使用されます。古い大型化されたパネルは、すべてのプラットフォームで削除されました。ネイティブバンドルビルダーと Docker ビルダーの両方が、そのインターフェイスをソースから再ビルドします。

Preview 10 はこれらの画面変更を含みます。以前のインストーラーや Docker イメージには、その版の画面が残るため、対応する Preview 10 のパッケージやイメージで更新してください。この M1 の手順で生成するのは ARM64 macOS 用 DMG です。Windows・Linux では、それぞれの[ネイティブビルド手順](RELEASING.ja.md#local-native-build)を使います。

Preview 10 は Windows のカメラ検出、サムネイル更新などのバックグラウンドメディア処理で、エラー出力を保持しながらコンソールウィンドウを非表示にします。以前のインストーラーの動作は変わりません。

現在のソースには、[完全な停止およびアンインストールの修正](STOP_AND_UNINSTALL.ja.md)も含まれています。インストール済みバンドルのテストでは、停止を要求し、API および MediaMTX のリスニングポートが閉じることを確認します。Mac ではさらに、カメラのストリーミング中に **Quit FlintEye** を選択し、インジケーターがオフになりアイコンが消えることを確認してから、FlintEye を再度開き、保存された設定が引き続き機能することを確認してください。

ローカルの M1 ビルドでは、ネイティブの AppKit 終了デリゲートテストも実行されます。インストール後、カメラのストリーミング中にメニューバーからの停止アクションと、Dock からの通常の終了アクションの両方をテストします。これらの物理デバイスの確認は引き続き必要です。
