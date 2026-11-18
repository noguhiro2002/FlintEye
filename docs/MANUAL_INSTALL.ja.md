<a id="run-from-source"></a>
# ソースからの実行

[English](MANUAL_INSTALL.md)

[Documentation](README.ja.md)

この手順は開発者向けです。一般ユーザーは[デスクトップインストーラー](INSTALL.ja.md)を使用してください。

<a id="requirements"></a>
## 必要条件

- Python 3.13または3.14（Windows/macOSでは3.14.10を使用）、Node.js 22.12+、npm
- `libx264`、`drawtext`、HTTP/HTTPS/RTSP、およびconcat-demuxerをサポートするFFmpeg/FFprobe
- PATH上の、または`bin/mediamtx`（Windowsでは`bin/mediamtx.exe`）にあるMediaMTX 1.21.2
- デスクトップランチャー用のTk。Linuxパッケージでは一般的に`python3-tk`と呼ばれます

<a id="linux-python-prerequisites"></a>
### Linux Pythonの前提条件

`-m venv`を実行する前に、実際に使用するPythonインタープリターの仮想環境サポートをインストールしてください。Debian/Ubuntuでは、これは別のパッケージに分割されています。ディストリビューションのデフォルトPythonの場合は`python3-venv`、または`python3.13-venv`などの一致するバージョンです。デスクトップ設定用に一致するTkパッケージもインストールしてください。`ensurepip`が利用できない場合は、そのvenvパッケージをインストールして不完全な環境を再作成してください。アプリケーション要件のインストールでは修復できません。

インタープリターは、上記のPythonのバージョン要件を引き続き満たす必要があります。ディストリビューションのデフォルトのPythonは古い可能性があるため、個別にインストールされたサポート対象のインタープリターと、一致するvenv/Tkコンポーネントを使用してください。オペレーティングシステムのPythonを置き換えたり削除したりしないでください。たとえば、Debianでパッケージ版Python 3.13を使用する場合：

```sh
sudo apt-get install python3.13-venv python3-tk
python3.13 -m venv .venv
```

リポジトリをクローンし、そのルートからコマンドを実行します：

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

Windowsでは`py -3.14 -m venv .venv`を使用し、`python`の代わりに`.venv\Scripts\python.exe`を使用してください。
パブリックソースはGitHub認証なしでクローンできます。以前のプライベートリポジトリを使用していた場合は、関連のない履歴をマージするのではなく、新しくチェックアウトを作成してください。

ランチャーは、パッケージと同じパスワード設定、ローカルデータディレクトリ、ブラウザUIを使用します。
デスクトップなしで実行するには、`python flinteye.py --headless`を使用します。生成された`setup-token`ファイルを読み込み、ローカルブラウザまたはSSHトンネルを通じて設定を完了します。
プロセス引数にパスワードを指定しないでください。

<a id="develop-the-frontend"></a>
## フロントエンドの開発

ホットリロード用の個別の開発スタックを使用します：

```sh
cp config/examples/.env.example.linux .env
python -m tools.manage_auth init-local --runtime-file runtime.json
python -m tools.start_orchestrator_stack --env-file .env --runtime-file runtime.json
```

それらのシステムでは、macOS/Windows環境のテンプレートを選択してください。
開発では独自の`runtime.json`を使用します。デスクトップアプリケーションと同じポートで実行しないでください。
APIおよびViteリスナーをループバックに維持してください。

[API reference](advanced/API.ja.md) · [Camera tools](advanced/CAMERA_TOOLS.ja.md) · [Frontend details](advanced/DEVELOPMENT.ja.md)

<a id="uninstall-a-source-environment"></a>
## ソース環境のアンインストール

ソースを削除する前に、デスクトップランチャーで構成されたログイン起動設定を無効にしてください。「Quit FlintEye」を選択するか、API、フロントエンド開発サーバー、またはツールを実行している各ターミナルでCtrl+Cを押して待機します。再起動するように構成された[systemdサービス](STOP_AND_UNINSTALL.ja.md#systemd)または[Composeデプロイメント](STOP_AND_UNINSTALL.ja.md#docker-compose)を停止および無効化してください。

`.env`、`runtime.json`、録画データ、およびチェックアウト内のその他のデータは保持されます。仮想環境がアクティブな場合は`deactivate`で非アクティブ化し、ファイルマネージャーを使用して専用のチェックアウトと仮想環境を削除してください。チェックアウト外の環境は個別に削除してください。デフォルトのデスクトップデータおよびカスタムの外部録画フォルダーは、意図的に削除しない限り保持されます。[ソースの削除と共有依存関係](STOP_AND_UNINSTALL.ja.md#manual-source-and-virtual-environment) · [オプションのデータ消去](STOP_AND_UNINSTALL.ja.md#permanently-erase-data-optional)

<a id="verify-changes"></a>
## 変更の検証

```sh
python -m unittest discover -s tests -v
npm --prefix frontend ci
npm --prefix frontend run build
python packaging/check_docs.py
```

pipを通したアプリケーションの配布は後回しにされています。`requirements.txt`のインストールでは、スタンドアロンのFlintEyeアプリケーションではなく依存関係がインストールされます。
