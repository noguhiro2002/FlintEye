<a id="advanced-reference-development"></a>

# 高度なリファレンス: 開発

[English](DEVELOPMENT.md)

[ドキュメント](../README.ja.md) · [手動インストール](../MANUAL_INSTALL.ja.md)

> これらは低レベルのソース/開発コマンドであり、リポジトリのルートから実行します。
> パッケージ化されたアプリケーションの場合は、[ユーザーガイド](../USER_GUIDE.ja.md)を使用してください。
> スタンドアロンのMediaMTXの保持およびサービス設定は、FlintEyeが管理するストレージには適用されません。
> リスナーはループバックに維持してください。LANアクセスには、[配信ガイド](../DISTRIBUTION.ja.md)で説明されている認証済みHTTPSプロキシを使用します。

<a id="12-web-ui-developer-reference"></a>

## 12. Web UI（開発者向けリファレンス）

フロントエンドのソースの場所:

- `frontend`

主要な構造:

- `frontend/src/App.tsx`: シェルレイアウトとページルーティング
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/pages/LiveViewPage.tsx`
- `frontend/src/pages/MultiviewPage.tsx`
- `frontend/src/pages/RecordingsPage.tsx`
- `frontend/src/api/client.ts`: APIクライアント

<a id="121-start"></a>

### 12.1 起動

推奨（API + MediaMTX + カメラワーカー + フロントエンドをまとめて起動）:

```bash
python3 -m tools.start_orchestrator_stack --env-file .env --runtime-file runtime.json
```

`frontend/package.json` または `frontend/package-lock.json` を更新する変更をプルした後は、
スタックを起動する前に、一度フロントエンドの依存関係を更新してください。
既存の `frontend/node_modules` は各マシンのローカルに存在するため、Gitでは更新されません。

```bash
cd frontend
npm ci
cd ..
```

PowerShellの場合:

```powershell
Set-Location .\frontend
npm ci
Set-Location ..
python -m tools.start_orchestrator_stack --env-file .env --runtime-file runtime.json
```

Viteがインポートされたパッケージを「解決できなかった (could not be resolved)」と報告した場合は、
同じ `npm ci` コマンドを実行してスタックを再起動してください。

<a id="1211-full-stop--cleanup"></a>

### 12.1.1 完全停止 / クリーンアップ

オーケストレーターの実行中に `ffmpeg` だけを強制終了しないでください。

理由:

- `flinteye_app/orchestrator_api.py` がカメラおよびマルチビューのワーカープロセスを監視しています
- `ffmpeg` のみを強制終了すると、スーパーバイザーはワーカーがクラッシュしたとみなして再起動します

正しいシャットダウンの順序:

1. `tools/start_orchestrator_stack.py` または `flinteye_app/orchestrator_api.py` を停止する
2. 次に残っているワーカープロセスを停止する
3. 必要に応じて、残存している `mediamtx` / `ffmpeg` を停止する

便利スクリプト:

```bash
./tools/stop_all.sh
```

手動コマンド:

Ctrl+Cでフォアグラウンドの開発スタックを停止します。正確なPIDを停止する前に残存プロセスを確認し、関係のないFFmpegやMediaMTXのプロセスを強制終了しないでください。

何も残っていないことを確認する:

```bash
ps -ax -o pid,ppid,command | rg "flinteye_app/orchestrator_api.py|tools/start_orchestrator_stack.py|flinteye_app/workers/uvc_to_rtsp.py|flinteye_app/workers/multiview_to_rtsp.py|mediamtx|ffmpeg"
```

オプションフラグ:

- `--api-host 127.0.0.1 --api-port 18080`
- `--ui-host 127.0.0.1 --ui-port 5173`
- `--skip-npm-install`（依存関係の自動インストールチェックをスキップ）
- `--npm-command npm`（`npm` コマンド名が異なる場合）

レガシー/手動でのフロントエンド起動:

```bash
cd frontend
npm ci
npm run dev
```

デフォルトURL:

- `http://127.0.0.1:5173`

Vite開発サーバーのプロキシ:

- `/api/*` -> `http://127.0.0.1:18080`

<a id="1212-access-from-other-devices-on-the-same-lan"></a>

### 12.1.2 同一LAN上の他のデバイスからのアクセス

APIとViteの開発サーバーは `127.0.0.1` に維持してください。他のデバイスからアクセスする場合は、
WebSocketサポートを含め、`/api` および `/media` をループバックAPIへのHTTPSリバースプロキシ経由でパッケージ版Web UIを公開してください。
サーバーの設定については、[コミュニティ配信ガイド](../DISTRIBUTION.ja.md)を参照してください。
管理者の一時的なアクセスには、`127.0.0.1:18080` へのSSHトンネルが適しています。

<a id="122-ui-features"></a>

### 12.2 UI機能

- サイドバーナビゲーション: Dashboard / Information / Settings / Live View / Multiview / Recordings
- Dashboard: オーケストレーターとプロセスのステータス
- Information:
  - カメラのRTSP/WebRTCエンドポイント
  - シンプルなカメラ設定（利用可能な場合は解像度/fps/ビットレート/エンコーダー）
  - マルチビュー設定の概要
- Settings:
  - `/api/v1/uvc/devices` からのUVC検出
  - UVCの提案/適用ワークフロー
  - IPカメラのドラフトテーブル
  - 共通フィールド用のBasicタブ（`ui`、`api`、`snapshot`、`mediamtx`、`recording`、`multiview`、`cameras`）
  - 完全な `runtime.json` 編集用のAdvancedタブ（置換 + 適用）
  - 管理者トークンが有効でない限り非表示
- Live View:
  - すべてのカメラのサムネイルグリッド（スナップショット）
  - サムネイルをクリックして単一カメラのWebRTC（iframe）を開く
- Multiview:
  - APIからのビューリスト
  - 選択した単一マルチビューのWebRTC（iframe）
- Recordings:
  - ストリームフィルター + APIからの録画ファイルリスト
  - 保存された動画ファイルのビルトインプレーヤー
  - ブラウザでの再生により、録画フォルダ外のプライベート再生キャッシュ内に一時的な再多重化（remux）MP4ファイルが作成されます。
    これらは `recording.playback_cache_delete_after`（デフォルトは `24h`、30秒ごとにチェック）経過後、またはシャットダウン時に期限切れとなります。
- フッターテキストは、runtime/UI設定（`ui.footer_text` または `WEBAPP_FOOTER_TEXT`）を介して設定可能です。

<a id="repository-layout"></a>

## リポジトリの構造

`flinteye.py` は、ソースおよび凍結バンドル（frozen-bundle）のエントリポイントです。アプリケーションは `flinteye_app/` に、その6つのワーカーモジュールは `flinteye_app/workers/` に、開発コマンドは `tools/` に配置されています。チェックアウトのルートから `python -m tools.manage_auth --help` または `python -m tools.start_orchestrator_stack --help` を使ってツールを実行してください。

リソースの検索では、ソース実行時はチェックアウトのルートを使用し、インストール済みビルドではPyInstallerが抽出したリソースディレクトリを使用します。ユーザー設定と録画は既存のデータディレクトリに残ります。別のディレクトリから `flinteye.py` の絶対パスを起動しても、リソースの検出場所は変わりません。

環境設定のサンプルは `config/examples/` に、環境変数リファレンスは [ENV_OPTIONS.md](ENV_OPTIONS.ja.md) に、開発用Composeは `deploy/` にあります。生成されたTypeScriptのビルド情報と出力されたVite設定は無視されます。代わりに `frontend/vite.config.ts` を編集してください。
