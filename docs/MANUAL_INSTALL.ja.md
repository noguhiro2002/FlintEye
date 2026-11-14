<a id="run-from-source"></a>
# ソースからの実行

[English](MANUAL_INSTALL.md)

[Documentation](README.ja.md)

この手順は開発者向けです。一般ユーザーは、リリースされたら[デスクトップインストーラー](INSTALL.ja.md)を使用してください。

<a id="requirements"></a>
## 要件

- Python 3.13または3.14（Windows/macOSでは3.14.10を使用）、Node.js 22.12+、npm
- `libx264`、`drawtext`、HTTP/HTTPS/RTSP、concat-demuxerをサポートするFFmpeg/FFprobe
- PATH上の、または`bin/mediamtx`（Windowsでは`bin/mediamtx.exe`）にあるMediaMTX 1.21.2
- デスクトップランチャー用のTk。Linuxパッケージでは一般的に`python3-tk`と呼ばれます

リポジトリをクローンし、ルートからコマンドを実行します：

```sh
git clone https://github.com/noguhiro2002/FlintEye.git
cd FlintEye
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -c packaging/constraints.txt -r requirements.txt -r packaging/requirements-build.txt
npm --prefix frontend ci
npm --prefix frontend run build
python flinteye.py
```

Windowsでは`python`の代わりに`py -3.14 -m venv .venv`を使用し、次に`.venv\Scripts\python.exe`を使用します。
公開ソースはGitHub認証なしでクローンできます。以前のプライベートリポジトリを使用していた場合は、関連のない履歴をマージするのではなく、新しくチェックアウトを作成してください。

ランチャーは、パッケージと同じパスワード設定、ローカルデータディレクトリ、ブラウザUIを使用します。
デスクトップなしで実行するには、`python flinteye.py --headless`を使用します。生成された`setup-token`ファイルを読み取り、ローカルブラウザまたはSSHトンネルを通じて設定を完了します。
プロセス引数にパスワードを指定しないでください。

<a id="develop-the-frontend"></a>
## フロントエンドの開発

ホットリロードには、個別の開発スタックを使用します：

```sh
cp config/examples/.env.example.linux .env
python -m tools.manage_auth init-local --runtime-file runtime.json
python -m tools.start_orchestrator_stack --env-file .env --runtime-file runtime.json
```

該当するシステムでは、macOS/Windows環境のテンプレートを選択してください。
開発では独自の`runtime.json`を使用します。デスクトップアプリケーションと同じポートで実行しないでください。
APIとViteリスナーをループバックに維持します。

[API reference](advanced/API.ja.md) · [Camera tools](advanced/CAMERA_TOOLS.ja.md) · [Frontend details](advanced/DEVELOPMENT.ja.md)

<a id="verify-changes"></a>
## 変更の検証

```sh
python -m unittest discover -s tests -v
npm --prefix frontend ci
npm --prefix frontend run build
python packaging/check_docs.py
```

pipを通じたアプリケーションの配布は後回しにされています。`requirements.txt`のインストールは、スタンドアロンのFlintEyeアプリケーションではなく依存関係をインストールします。
