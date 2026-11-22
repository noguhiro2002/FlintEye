<a id="flinteye-environment-options"></a>

# FlintEye 環境オプション

[English](ENV_OPTIONS.md)

[ドキュメント](../README.ja.md)

> これらはリポジトリルートから実行する低レベルのソース／開発用コマンドです。
> パッケージ版アプリケーションについては、[ユーザーガイド](../USER_GUIDE.ja.md)を参照してください。
> 単体 MediaMTX の保持期間およびサービス設定は、FlintEye 管理下のストレージには適用されません。
> リスナーはループバックに維持してください。LAN アクセスには、[配布ガイド](../DISTRIBUTION.ja.md)で説明されている認証付き HTTPS プロキシを使用します。

このドキュメントでは、コードベースが現在読み取る環境変数の一覧を示します。
ベースとなるファイル：

- `flinteye_app/orchestrator_store.py`
- `flinteye_app/workers/uvc_to_rtsp.py`
- `flinteye_app/workers/multiview_to_rtsp.py`
- `flinteye_app/orchestrator_models.py`
- `flinteye_app/orchestrator_supervisor.py`
- `flinteye_app/orchestrator_api.py`

<a id="common-rules"></a>

## 共通ルール

- パーサーが受け付けるブール値：
  - true: `1`, `true`, `yes`, `on`
  - false: `0`, `false`, `no`, `off`
- CSV形式のリストは、カンマ、セミコロン、または改行を受け付けます。
- 空の値は通常「未設定 / オーバーライドなし」を意味しますが、一度有効化すると空にできないフィールドもあります。

<a id="important-caveats"></a>

## 重要な注意事項

- `MTX_CONTROL_MODE`
  - スキーマ上の値: `windows_service`, `systemd`, `launchd`, `direct`, `external`, `docker_compose`
  - `OrchestratorSupervisor` によって実際に実装されている値: `windows_service`, `systemd`, `launchd`, `direct`, `external`
  - `docker_compose` はモデル内に存在しますが、スーパーバイザーではまだ実装されていません。
- `AUTH_PROVIDER`
  - スキーマ上の値: `local`, `legacy_token`, `oidc`
  - 現在実際に使用可能な値: `local`, `legacy_token`
  - `oidc` はモデルに存在しますが、APIは現在OIDC認証フローに対して `501` を返します。
- `UVC_LATENCY_PRESET`
  - `flinteye_app/workers/uvc_to_rtsp.py` は現在 `low` のみを受け付けます
  - 通常/デフォルトの動作にするには、未設定のままにしてください
  - `normal` は README に記載されていますが、現在の UVC パーサーでは受け付けられません

<a id="api--auth"></a>

## API / 認証

- `API_HOST`
  - 任意のホストまたはIP文字列
  - 例: `127.0.0.1`, `0.0.0.0`, `192.168.1.10`
- `API_PORT`
  - 整数 `1..65535`

<a id="web-ui--vite-dev-server"></a>

## Web UI / Vite 開発サーバー

- `WEBUI_HOST`
  - 任意のホストまたはIP文字列
  - Vite開発サーバーのバインドホストとして `tools/start_orchestrator_stack.py` が使用します
- `WEBUI_PORT`
  - 整数 `1..65535`
  - Vite開発サーバーのバインドポートとして `tools/start_orchestrator_stack.py` が使用します
- `WEBUI_API_PROXY_TARGET`
  - Viteの `/api/*` 開発用プロキシのオプショナルなHTTPオリジン
  - 例: `http://127.0.0.1:18080`
  - 未設定の場合、`tools/start_orchestrator_stack.py` は `API_PORT` からこれを導出します
- `WEBUI_MTX_API_PROXY_TARGET`
  - Viteの `/v3/*` 開発用プロキシのオプショナルなHTTPオリジン
  - 例: `http://127.0.0.1:9997`
  - 未設定の場合、`tools/start_orchestrator_stack.py` はデフォルトで `http://127.0.0.1:9997` に設定します
- `VITE_API_PROXY_TARGET`
  - `frontend/vite.config.*` が直接読み取る環境変数
  - 通常は `tools/start_orchestrator_stack.py` によってインジェクションされます
  - デフォルト以外のAPIプロキシターゲットが必要な手動での `npm run dev` 起動時に使用してください
- `VITE_MTX_API_PROXY_TARGET`
  - `frontend/vite.config.*` が直接読み取る環境変数
  - 通常は `tools/start_orchestrator_stack.py` によってインジェクションされます
  - デフォルト以外のMediaMTX APIプロキシターゲットが必要な手動での `npm run dev` 起動時に使用してください
- `VITE_API_BASE`
  - `frontend/src/api/client.ts` 内のブラウザクライアントによって読み取られます
  - 開発時は通常未設定のままにし、代わりにViteプロキシを使用してください
  - これを別のオリジンに直接向ける場合は、APIが現在CORSミドルウェアを有効にしていないことに注意してください
- `AUTH_PROVIDER`
  - `local`
  - `legacy_token`
  - `oidc` (プレースホルダーのみ、未実装)
- `AUTH_VIEWER_AUTH_REQUIRED`
  - ブール値
- `AUTH_SESSION_COOKIE_NAME`
  - 任意の空でない文字列
- `AUTH_SESSION_TTL_SEC`
  - 整数 `> 0`
- `AUTH_SESSION_SECRET`
  - 任意の文字列
  - `tools/manage_auth.py` を経由して生成することを推奨します
- `AUTH_LOCAL_ADMIN_USERNAME`
  - 任意の空でない文字列
- `AUTH_LOCAL_ADMIN_PASSWORD_HASH`
  - `tools/manage_auth.py` によって生成された PBKDF2 ハッシュ文字列
- `AUTH_LOCAL_VIEWER_USERNAME`
  - 任意の空でない文字列
- `AUTH_LOCAL_VIEWER_PASSWORD_HASH`
  - `tools/manage_auth.py` によって生成された PBKDF2 ハッシュ文字列
- `AUTH_OIDC_ISSUER_URL`
  - URL文字列
  - 現在はプレースホルダーのみ
- `AUTH_OIDC_CLIENT_ID`
  - 文字列
  - 現在はプレースホルダーのみ
- `AUTH_OIDC_CLIENT_SECRET`
  - 文字列
  - 現在はプレースホルダーのみ
- `AUTH_OIDC_REDIRECT_URI`
  - URL文字列
  - 現在はプレースホルダーのみ
- `AUTH_OIDC_SCOPES`
  - 任意の空でない文字列
  - 例: `openid profile email`
- `API_ADMIN_TOKEN`
  - 任意の文字列
  - `AUTH_PROVIDER=legacy_token` と共に使用されます
- `API_VIEWER_TOKEN`
  - 任意の文字列
  - `AUTH_PROVIDER=legacy_token` と共に使用されます
- `API_BEARER_TOKEN`
  - 任意の文字列
  - 管理者トークンのレガシーなフォールバック
- `API_VIEWER_AUTH_REQUIRED`
  - ブール値
  - レガシートークンのパスでのみ有効

<a id="ui--logging--snapshots"></a>

## UI / ロギング / スナップショット

- `WEBAPP_TITLE`
  - 任意の空でない文字列
- `WEBAPP_SIDEBAR_TITLE`
  - 任意の空でない文字列
- `WEBAPP_FOOTER_TEXT`
  - 任意の空でない文字列
- `SNAPSHOT_TIMEOUT_SEC`
  - 数値 `> 0` かつ `<= 120`
- `LOG_DIR`
  - 任意の空でないパス文字列
- `LOG_LEVEL`
  - `DEBUG`
  - `INFO`
  - `WARNING`
  - `ERROR`
  - `CRITICAL`
  - 検証前に大文字に変換されるため、小文字でも動作します
- `LOG_RETENTION`
  - 空 / 未設定
  - または、アプリが保持期間のメタデータとして使用する、任意の空でない持続時間のような文字列

<a id="mediamtx"></a>

## MediaMTX

- `MTX_CONTROL_MODE`
  - 現在サポートされている値:
    - `windows_service`
    - `systemd`
    - `launchd`
    - `direct`
    - `external`
  - スキーマには存在するが未実装の値:
    - `docker_compose`
- `MTX_SERVICE_NAME`
  - 選択されたコントロールモードに適したサービスラベル
  - 例:
    - Linux systemd: `mediamtx`
    - macOS Homebrew launchd: `homebrew.mxcl.mediamtx`
    - Windows サービス: `mediamtx`
- `MTX_AUTOSTART_ON_API_START`
  - ブール値
- `MTX_RTSP_BASE_URL`
  - RTSPベースURL
  - 例: `rtsp://127.0.0.1:8554`
- `MTX_INTERNAL_RTSP_BASE_URL`
  - 同一ホスト上のオーケストレーター管理によるローカルパブリッシャーが使用する、オプショナルなRTSPベースURL
  - デフォルトは `MTX_RTSP_BASE_URL`
  - 例: `rtsp://127.0.0.1:8554`
- `MTX_WEBRTC_BASE_URL`
  - MediaMTX WebRTCビューア用のHTTPベースURL
  - 例: `http://127.0.0.1:8889`
- `MTX_MANAGED_ENABLED`
  - ブール値
  - MediaMTX の `global` / `paths` データのREST側からの管理を有効にします
- `MTX_CONFIG_PATH`
  - `mediamtx.yml` へのパス
- `MTX_DIRECT_COMMAND`
  - `direct` モード用のシェルスタイルのコマンドライン
  - 例: `/opt/homebrew/opt/mediamtx/bin/mediamtx /opt/homebrew/etc/mediamtx/mediamtx.yml`
- `MTX_DIRECT_WORKDIR`
  - `direct` モード用の作業ディレクトリパス

<a id="uvc-ingest"></a>

## UVC インジェスト

- `UVC_PROFILES`
  - プロファイル名のCSVリスト
  - 例: `cam1,cam2`
- `UVC_PROFILE`
  - 単一のデフォルトプロファイル名
  - 例: `cam1`
- `UVC_CAMERA_NAME`
  - オーバーレイに表示される任意の空でないラベル
- `UVC_RTSP_URL`
  - 完全なRTSP出力URL
- `UVC_INPUT_DRIVER`
  - `auto`
  - `v4l2`
  - `avfoundation`
  - `dshow`
- `UVC_DEVICE`
  - 自由形式のデバイス識別子（ドライバーに依存）
  - 例:
    - `v4l2`: `/dev/video0`
    - `avfoundation`: `0:none` または `FaceTime HD Camera:none`
    - `dshow`: `Integrated Camera` または `video=Integrated Camera`
- `UVC_FFMPEG_BIN`
  - 実行ファイルのパスまたはコマンド名
  - 例: `ffmpeg`
- `UVC_LOGLEVEL`
  - ffmpegのログレベル文字列
  - 一般的な値: `error`, `warning`, `info`, `debug`
- `UVC_ENCODER`
  - `auto`
  - またはお使いのビルドで使用可能な任意のffmpeg H.264エンコーダー
  - 一般的な例:
    - macOS: `h264_videotoolbox`, `libx264`
    - Linux: `h264_v4l2m2m`, `h264_nvenc`, `h264_qsv`, `h264_amf`, `libx264`
    - Windows: `h264_qsv`, `h264_amf`, `h264_nvenc`, `libx264`
- `UVC_LATENCY_PRESET`
  - `low`
  - または、通常/デフォルトの動作にするには未設定のままにする
- `UVC_QUALITY_PRESET`
  - `high`
  - `standard`
  - `low`
- `UVC_WIDTH`
  - 正の整数
- `UVC_HEIGHT`
  - 正の整数
- `UVC_FPS`
  - 正の整数
- `UVC_INPUT_FORMAT`
  - 自由形式の入力フォーマット文字列
  - 例: `mjpeg`, `yuyv422`
- `UVC_RTBUFSIZE`
  - ffmpegのバッファサイズ文字列
  - 例: `8M`, `128M`, `256M`
- `UVC_BITRATE`
  - ffmpegのビットレート文字列
  - 例: `1M`, `2M`, `4M`
- `UVC_MAXRATE`
  - ffmpegのmaxrate文字列
  - 例: `1M`, `2M`, `4M`
- `UVC_BUFSIZE`
  - ffmpegのbufsize文字列
  - 例: `1M`, `2M`, `4M`, `8M`
- `UVC_GOP`
  - 正の整数
- `UVC_THREAD_QUEUE_SIZE`
  - 正の整数
- `UVC_BFRAMES`
  - 整数 `>= 0`
- `UVC_FONT_SIZE`
  - 正の整数
- `UVC_FONTFILE`
  - フォントファイルのパス
- `UVC_X264_PRESET`
  - libx264のプリセット文字列
  - 一般的な値:
    - `ultrafast`
    - `superfast`
    - `veryfast`
    - `faster`
    - `fast`
    - `medium`
    - `slow`
    - `slower`
    - `veryslow`
- `UVC_DRY_RUN`
  - ブール値

プロファイルごとのオーバーライドは、`UVC_<PROFILE>_...` の形式でサポートされています。
例:

- `UVC_CAM2_DEVICE=/dev/video1`
- `UVC_CAM2_CAMERA_NAME=UVC-CAM-02`
- `UVC_CAM2_RTSP_URL=rtsp://127.0.0.1:8554/uvc_cam2`

<a id="ip-camera-ingest"></a>

## IPカメラ インジェスト

- `MTX_IP_PATHS`
  - MediaMTXパス名のCSVリスト
  - 例: `ipcam1,ipcam2`
- `MTX_IP_<TOKEN>_SOURCE`
  - そのIPカメラのソースRTSP URL
- `MTX_IP_<TOKEN>_ENABLED`
  - ブール値

Settings > IP Cameras 画面では、環境変数ではなく `runtime.json` に保存されるカメラごとのランタイム設定を追加できます：

- `timestamp_mode`
  - `auto`: ライブRTSPタイムスタンプのリレー開始時の計測、および `source`、`wallclock`、`cfr` の選択を行う
  - `source`: カメラから提供されたタイムスタンプを維持する
  - `wallclock`: 再エンコードを行わずに、信頼性の低いカメラのタイムスタンプを置き換える
  - `cfr`: 固定フレームレートを生成し、libx264で再エンコードする
- `cfr_fps`
  - `timestamp_mode` が `cfr` に解決されるとき使用されるターゲットフレームレート
- `onvif_mode`
  - `auto`: WS-DiscoveryでソースURLのホストに一致するカメラを探します。見つからない場合は、Tapo用のTCP 2020を含む一般的なHTTP(S)ポートを同じカメラで試します。
  - `manual`: 必要に応じてデフォルト以外のポートやパスを含む、完全に設定されたONVIFデバイスサービスURLを使用する
  - `disabled`: ONVIFの検査をスキップし、RTSPのタイミングのみを計測する
- `onvif_address`, `onvif_username`, `onvif_password`
  - オプショナルな手動ONVIF接続設定。個別のONVIF資格情報が提供されない場合は、ソースURLの資格情報が使用されます。

**Inspect camera** アクションは、デバイス/ファームウェア情報、メディアプロファイル、観測されたフレームレート、タイムスタンプの逆転、大きなギャップ、および推奨されるタイムスタンプモードをレポートします。
ONVIF機能の処理はメーカーおよびモデルに依存しません。アドバタイズされたサービスXAddrが尊重され、利用可能な場合はMedia2が優先され、フォールバックとしてMedia1が使用され、ONVIFの実装が部分的な場合や存在しない場合でもRTSPタイミング検査が無効化されることはありません。

例:

- `MTX_IP_PATHS=ipcam1`
- `MTX_IP_IPCAM1_SOURCE=rtsp://user:pass@192.168.1.50:554/stream1`
- `MTX_IP_IPCAM1_ENABLED=true`

<a id="multiview"></a>

## マルチビュー

- `MV_ENABLED`
  - ブール値
- `MV_SOURCE_MODE`
  - `env`
  - `api`
  - `hybrid`
- `MV_SOURCE_PATHS`
  - ソースストリームパスのCSVリスト
- `MV_AUTO_PLACEHOLDER_MISSING_SOURCES`
  - `true`
  - `false`
  - `true` の場合、MediaMTXに見つからない設定済みソースは、マルチビュー出力全体を失敗させる代わりに `No Stream` タイルとして描画されます。
- `MV_MTX_API_URL`
  - MediaMTXパス一覧APIへのURL
- `MV_INPUT_RTSP_BASE_URL`
  - ソースストリーム用のRTSPベースURL
- `MV_OUTPUT_RTSP_BASE_URL`
  - 生成されたマルチビューストリーム用のRTSPベースURL
- `MV_OUTPUT_PREFIX`
  - 任意の空でない文字列
  - 例: `multiview`
- `MV_MAX_SOURCES`
  - 整数 `2..32`
- `MV_TILE_COUNT`
  - 整数 `2..32`
- `MV_CANVAS_WIDTH`
  - 正の整数
- `MV_CANVAS_HEIGHT`
  - 正の整数
- `MV_GRID_COLUMNS`
  - 正の整数
  - または、自動グリッド幅にする場合は未設定のままにする
- `MV_SLOT_POSITIONS`
  - セミコロン区切りの `x,y,w,h` エントリ
  - 例: `0,0,960,540;960,0,960,540;0,540,960,540;960,540,960,540`
- `MV_VIEW_<N>_SLOT_POSITIONS`
  - 同じ `x,y,w,h;...` 形式による、ビューごとのスロットオーバーライド
  - 例: `MV_VIEW_1_SLOT_POSITIONS=0,0,1920,1080`
- `MV_FPS`
  - 正の整数
- `MV_LATENCY_PRESET`
  - `low`
  - `normal`
- `MV_ENCODER`
  - `auto`
  - またはお使いのビルドで使用可能な任意のffmpeg H.264エンコーダー
- `MV_QUALITY_PRESET`
  - `high`
  - `standard`
  - `low`
- `MV_BITRATE`
  - ffmpegのビットレート文字列
- `MV_MAXRATE`
  - ffmpegのmaxrate文字列
- `MV_BUFSIZE`
  - ffmpegのbufsize文字列
- `MV_GOP`
  - 正の整数
- `MV_BFRAMES`
  - 整数 `>= 0`
- `MV_X264_PRESET`
  - libx264のプリセット文字列
  - 一般的な値:
    - `ultrafast`
    - `superfast`
    - `veryfast`
    - `faster`
    - `fast`
    - `medium`
    - `slow`
    - `slower`
    - `veryslow`
- `MV_RESTART_BACKOFF_SEC`
  - 数値 `>= 0`
- `MV_INPUT_STALL_TIMEOUT_SEC`
  - 数値 `>= 0`
  - 応答のないRTSP入力をFFmpegがスタックしているとみなすまでの秒数
  - `0` はこのタイムアウトを無効にします
- `MV_INPUT_STALL_TIMEOUT_OPTION`
  - `auto`
  - `rw_timeout`
  - `stimeout`
  - `timeout`
  - `none`
  - 特定のFFmpegビルドで固定オプションが必要な場合を除き、番目の `auto` を使用してください
- `MV_INPUT_THREAD_QUEUE_SIZE`
  - 正の整数。通常モードではデフォルト `128` で、低遅延モードでは最大 `32` に制限されます
- `MV_INPUT_HEALTHCHECK_ENABLED`
  - ブール値。期待されるすべてのMediaMTXパス、RTSPリーダー、およびバイトの進行状況を監視します
- `MV_INPUT_HEALTHCHECK_INTERVAL_SEC`
  - 正の数値。デフォルト `5`
- `MV_INPUT_ISOLATION_THRESHOLD`
  - 正の整数。デフォルト `3`
  - 繰り返し失敗した場合、影響を受けるタイルのみが `No Stream` に置き換えられます
- `MV_INPUT_RETRY_INTERVAL_SEC`
  - 正の数値。デフォルト `30`
- `MV_STATUS_FILE`
  - エフェメラルなJSONステータスパス。デフォルト `./logs/runtime/multiview_status.json`
- `MV_FFMPEG_BIN`
  - 実行ファイルのパスまたはコマンド名
- `MV_LOGLEVEL`
  - ffmpegのログレベル文字列
  - 一般的な値: `error`, `warning`, `info`, `debug`
- `MV_DRY_RUN`
  - ブール値
- `MV_ONCE`
  - ブール値
- `MV_VERBOSE`
  - ブール値
- `MV_MAINTENANCE_ENABLED`
  - ブール値
- `MV_MAINTENANCE_RESTART_INTERVAL_SEC`
  - 数値 `> 0`
- `MV_MAINTENANCE_ALIGN_WITH_RECORD_SEGMENTS`
  - ブール値
- `MV_MAINTENANCE_RESTART_OFFSET_SEC`
  - 数値 `>= 0`

<a id="recording"></a>

## 録画

- `MTX_RECORD_AUTO_APPLY`
  - ブール値
- `MTX_RECORD_ROOT`
  - 任意の空でないパス文字列
- `MTX_RECORD_FORMAT`
  - `fmp4`
  - `mpegts`
- `MTX_RECORD_PART_DURATION`
  - 任意の空でない持続時間文字列
  - 例: `1s`
- `MTX_RECORD_MAX_PART_SIZE`
  - 任意の空でないサイズ文字列
  - 例: `50M`
- `MTX_RECORD_SEGMENT_DURATION`
  - 任意の空でない持続時間文字列
  - 例: `10m`
- `MTX_RECORD_DELETE_AFTER`
  - 任意の空でない持続時間文字列
  - 例: `168h`
- `PLAYBACK_CACHE_DELETE_AFTER`
  - 再生キャッシュの保持期間。API起動時および5分ごとにチェックされます
  - `ms`、`s`、`m`、`h`、または `d` を使用する、ゼロより大きい持続時間
  - デフォルト: `24h`
- `MTX_RECORD_INCLUDE_MULTIVIEW`
  - ブール値
- `MTX_MULTI_VIEW_MAX_COUNT`
  - 整数 `>= 1`
- `MTX_RECORD_PATHS`
  - 録画するパスのCSVリスト
  - 設定済みのカメラパスを自動使用する場合は空のままにしてください
