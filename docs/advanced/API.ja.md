<a id="advanced-reference-api"></a>

# 詳細リファレンス: API

[English](API.md)

[ドキュメント](../README.ja.md) · [手動インストール](../MANUAL_INSTALL.ja.md)

> これらはリポジトリルートから実行する低レベルのソース／開発向けコマンドです。
> パッケージ版アプリケーションについては、[ユーザーガイド](../USER_GUIDE.ja.md)を参照してください。
> 単体 MediaMTX の保持設定およびサービス設定は、FlintEye が管理するストレージには適用されません。
> リスナーはループバックに維持してください。LAN アクセスには、[配布ガイド](../DISTRIBUTION.ja.md)で説明されている認証付き HTTPS プロキシを使用します。

<a id="11-unified-camera-orchestrator-api-uvc--multiview--mediamtx"></a>

## 11. FlintEye API（UVC / MultiView / MediaMTX）

`flinteye_app/orchestrator_api.py` は、以下を制御するための単一の REST API を提供します。

- カメラごとの UVC インジェストプロセス（`flinteye_app/workers/uvc_to_rtsp.py`）
- カメラごとの IP カメラインジェストプロセス
- マルチビュー合成プロセス（`flinteye_app/workers/multiview_to_rtsp.py`）
- MediaMTX サービス（Windows サービス / systemd / launchd / direct / external モード）
- ランタイム設定の永続化（`runtime.json`）
- スナップショットのキャプチャおよびストリームアドレスの取得

<a id="111-install-dependencies"></a>

### 11.1 依存関係のインストール

```bash
python3 -m pip install fastapi uvicorn
# or
python3 -m pip install -r requirements.txt
```

<a id="112-required-env-keys"></a>

### 11.2 必須の `.env` キー

完全な一覧については、OS ごとのテンプレートを参照してください。

- `config/examples/.env.example.mac`
- `config/examples/.env.example.windows`
- `config/examples/.env.example.linux`

推奨される最小限のキー:

- `API_HOST=127.0.0.1`
- `API_PORT=18080`
- `AUTH_PROVIDER=local`
- `AUTH_VIEWER_AUTH_REQUIRED=true`
- `AUTH_SESSION_COOKIE_NAME=orch_session`
- `AUTH_SESSION_TTL_SEC=43200`
- `AUTH_LOCAL_ADMIN_USERNAME=admin`
- `AUTH_LOCAL_VIEWER_USERNAME=viewer`
- `AUTH_SESSION_SECRET=`（推奨: 手動ではなく `tools/manage_auth.py` で初期化）
- `AUTH_LOCAL_ADMIN_PASSWORD_HASH=`（推奨: 手動ではなく `tools/manage_auth.py` で初期化）
- `AUTH_LOCAL_VIEWER_PASSWORD_HASH=`（推奨: 手動ではなく `tools/manage_auth.py` で初期化）
- `API_ADMIN_TOKEN=` / `API_VIEWER_TOKEN=` / `API_BEARER_TOKEN=`（`AUTH_PROVIDER=legacy_token` を使用する場合のみ）
- `SNAPSHOT_TIMEOUT_SEC=3.0`（`/snapshot` がタイムアウトを返す場合は増やしてください）
- `LOG_DIR=./logs`
- `LOG_LEVEL=ERROR`
- `LOG_RETENTION=`（空欄 = `MTX_RECORD_DELETE_AFTER` に従う）
- `WEBAPP_TITLE=Unified Camera Orchestrator`
- `WEBAPP_SIDEBAR_TITLE=Orchestrator UI`
- `WEBAPP_FOOTER_TEXT=© 2026 Noguhiro. Sustainable Use License + additional permission.`
- `MTX_CONTROL_MODE=windows_service|systemd|launchd|direct|external`
- `MTX_SERVICE_NAME=mediamtx`
- `MTX_AUTOSTART_ON_API_START=true`（デフォルト）
- `MTX_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MTX_INTERNAL_RTSP_BASE_URL=rtsp://127.0.0.1:8554` 同一ホスト上のローカルパブリッシャープロセス用（任意、デフォルトは `MTX_RTSP_BASE_URL`）
- `MTX_WEBRTC_BASE_URL=http://127.0.0.1:8889`
- `MTX_MANAGED_ENABLED=false`（REST 経由で mediamtx.yml のグローバル/パスを編集する場合は `true` に設定）
- `MTX_CONFIG_PATH=<path-to-mediamtx.yml>`
- `MTX_RECORD_AUTO_APPLY=true`（デフォルト）

設定の優先順位:

- `runtime.json`（API で更新された値） > `.env` > 組み込みのデフォルト値

MediaMTX を（この API の外部で）手動起動する場合は、以下を設定してください。

- `MTX_CONTROL_MODE=external`
- `MTX_AUTOSTART_ON_API_START=false`（推奨）

`external` モードでは、`/control/start|stop|restart` はプロセスを管理せず、手動操作の案内を返します。

<a id="113-start-api-server"></a>

### 11.3 API サーバーの起動

```bash
python3 -m flinteye_app.orchestrator_api --env-file .env --runtime-file runtime.json
```

<a id="114-authentication"></a>

### 11.4 認証

推奨されるローカル認証のブートストラップ:

```bash
python3 -m tools.manage_auth init-local --runtime-file runtime.json
```

このコマンドは以下を実行します。

- パスワードハッシュを生成する
- セッションシークレットがない場合は生成する
- 認証ブロックを `runtime.json` に書き込む

ローカル認証のキー:

- `AUTH_PROVIDER=local`
- `AUTH_VIEWER_AUTH_REQUIRED=true|false`
- `AUTH_SESSION_COOKIE_NAME`
- `AUTH_SESSION_TTL_SEC`
- `AUTH_SESSION_SECRET`
- `AUTH_LOCAL_ADMIN_USERNAME`
- `AUTH_LOCAL_ADMIN_PASSWORD_HASH`
- `AUTH_LOCAL_VIEWER_USERNAME`
- `AUTH_LOCAL_VIEWER_PASSWORD_HASH`

レガシートークンモードも引き続きサポートされています。

- `AUTH_PROVIDER=legacy_token`
- `API_ADMIN_TOKEN`
- `API_VIEWER_TOKEN`
- `API_VIEWER_AUTH_REQUIRED=true|false`
- `API_BEARER_TOKEN`（レガシーフォールバック）

<a id="115-logging"></a>

### 11.5 ロギング

現在の実装では以下が出力されます。

- `logs/orchestrator.log`: オーケストレーター／API ランタイムログ
- `logs/uvc_cam1.log`, `logs/uvc_cam2.log`, ...: カメラごとのワーカーログ
- `logs/multiview.log`: マルチビューワーカーログ
- `logs/mediamtx.log`: MediaMTX direct モードのログ

ローテーションは日次で有効になっています。ローテーションされた古いログは保持期間に従って削除されます。

主なロギングキー:

- `LOG_DIR=./logs`
- `LOG_LEVEL=ERROR`
- `LOG_RETENTION=`: 空欄は `recording.record_delete_after` / `MTX_RECORD_DELETE_AFTER` を使用することを意味します
- `UVC_LOGLEVEL=error`
- `MV_LOGLEVEL=error`

パブリック（トークン不要）エンドポイント:

- `GET /api/v1/health`
- `GET /api/v1/status`

Viewer エンドポイント:

- 監視／表示／スナップショット／録画 API
- `API_VIEWER_AUTH_REQUIRED=false` の場合のみトークンは任意です

Admin エンドポイント:

- 設定／制御／書き込み API
- 設定されている場合、常に `API_ADMIN_TOKEN` が必要です

<a id="115-api-documents-swagger--redoc"></a>

### 11.5 API ドキュメント（Swagger / ReDoc）

API サーバーが稼働している場合:

- Swagger UI: `http://127.0.0.1:18080/docs`
- ReDoc: `http://127.0.0.1:18080/redoc`
- OpenAPI JSON: `http://127.0.0.1:18080/openapi.json`

認証が有効な場合は、Swagger UI で `Authorize` をクリックし、以下を入力してください。

- `Bearer <API_ADMIN_TOKEN>`（または閲覧専用エンドポイント用の Viewer トークン）

<a id="116-main-endpoints"></a>

### 11.6 主なエンドポイント

- `camera_id` は MediaMTX のパス名と完全に一致します（例: `uvc_cam1`, `ipcam2`）
- `GET /api/v1/health`
- `GET /api/v1/status`
- `GET /api/v1/status/processes`
- `GET /api/v1/status/mediamtx`
- `POST /api/v1/control/start`
- `POST /api/v1/control/stop`
- `POST /api/v1/control/restart`
- `GET /api/v1/config/effective`
- `GET /api/v1/config/runtime`
- `PUT /api/v1/config/runtime`
- `PATCH /api/v1/config/runtime`
- `POST /api/v1/config/apply`
- `GET /api/v1/uvc/devices`
- `GET /api/v1/uvc/devices/{device_id}`
- `POST /api/v1/uvc/devices/{device_id}/suggest`
- `POST /api/v1/uvc/devices/{device_id}/apply`
- `GET /api/v1/mediamtx/config`
- `PATCH /api/v1/mediamtx/config`
- `POST /api/v1/mediamtx/config/apply`
- `GET /api/v1/cameras`
- `POST /api/v1/cameras`
- `GET /api/v1/cameras/{camera_id}`
- `PATCH /api/v1/cameras/{camera_id}`
- `DELETE /api/v1/cameras/{camera_id}`
- `POST /api/v1/cameras/{camera_id}/enable`
- `POST /api/v1/cameras/{camera_id}/disable`
- `GET /api/v1/viewer/cameras`
- `GET /api/v1/viewer/info`
- `GET /api/v1/cameras/{camera_id}/addresses`
- `GET /api/v1/cameras/{camera_id}/snapshot`
- `GET /api/v1/multiview`
- `PATCH /api/v1/multiview`
- `POST /api/v1/multiview/enable`
- `POST /api/v1/multiview/disable`
- `GET /api/v1/multiview/views`
- `GET /api/v1/multiview/views/{view_id}/addresses`
- `GET /api/v1/multiview/views/{view_id}/snapshot`
- `GET /api/v1/streams/{stream_id}/addresses`
- `GET /api/v1/recordings/streams`
- `GET /api/v1/recordings`
- `GET /api/v1/recordings/files/{file_id}`

<a id="117-quick-api-examples"></a>

### 11.7 クイック API 例

```bash
ADMIN_TOKEN="change-this-token"
VIEWER_TOKEN="change-this-viewer-token"
BASE="http://127.0.0.1:18080"
ADMIN_AUTH="Authorization: Bearer ${ADMIN_TOKEN}"
VIEWER_AUTH="Authorization: Bearer ${VIEWER_TOKEN}"
```

ヘルス／ステータス:

```bash
curl "$BASE/api/v1/health"
curl "$BASE/api/v1/status"
```

検出された UVC カメラの一覧取得:

```bash
curl -H "$ADMIN_AUTH" "$BASE/api/v1/uvc/devices"
```

1 台の UVC デバイスに対する推奨設定の取得:

```bash
curl -X POST "$BASE/api/v1/uvc/devices/<device_id>/suggest" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"profile":"cam3","path":"uvc_cam3","camera_name":"UVC-CAM-03","use_device_index":false}'
```

検出された UVC デバイスをランタイムとプロセスに直接適用:

```bash
curl -X POST "$BASE/api/v1/uvc/devices/<device_id>/apply" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"profile":"cam3","path":"uvc_cam3","camera_name":"UVC-CAM-03"}'
```

1 台のカメラの無効化／有効化:

```bash
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/cameras/uvc_cam1/disable"
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/cameras/uvc_cam1/enable"
```

マルチビューの無効化／有効化:

```bash
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/multiview/disable"
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/multiview/enable"
```

ランタイム設定のパッチ適用（例: マルチビューのビットレート変更）:

```bash
curl -X PATCH "$BASE/api/v1/config/runtime" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"multiview":{"quality":{"bitrate":"2M","maxrate":"2M","bufsize":"2M"}}}'
```

MediaMTX 管理設定のパッチ適用（例: API リスナーを有効化し、パスごとのソースを設定）:

```bash
curl -X PATCH "$BASE/api/v1/mediamtx/config" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "managed": {
      "enabled": true,
      "global": {
        "api": true,
        "apiAddress": ":9997"
      },
      "paths": {
        "ipcam1": {
          "source": "rtsp://username:password@192.168.1.101:554/stream1",
          "sourceOnDemand": true
        }
      }
    },
    "recording": {
      "record_segment_duration": "1m",
      "record_delete_after": "5m",
      "playback_cache_delete_after": "24h"
    }
  }'
```

現在の MediaMTX 設定状態の取得／適用:

```bash
curl -H "$ADMIN_AUTH" "$BASE/api/v1/mediamtx/config"
curl -X POST -H "$ADMIN_AUTH" "$BASE/api/v1/mediamtx/config/apply"
```

スナップショットの取得:

```bash
curl -H "$VIEWER_AUTH" "$BASE/api/v1/cameras/uvc_cam1/snapshot" --output cam1.jpg
curl -H "$VIEWER_AUTH" "$BASE/api/v1/multiview/views/multiview_1/snapshot" --output mv1.jpg
```

実行時にスナップショットのタイムアウトを延長（例: 8 秒）:

```bash
curl -X PATCH "$BASE/api/v1/config/runtime" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"snapshot":{"timeout_sec":8.0}}'
```

RTSP/WebRTC アドレスの取得:

```bash
curl -H "$VIEWER_AUTH" "$BASE/api/v1/cameras/uvc_cam1/addresses"
curl -H "$VIEWER_AUTH" "$BASE/api/v1/streams/multiview_1/addresses"
```

録画の一覧取得／再生:

```bash
curl -H "$VIEWER_AUTH" "$BASE/api/v1/recordings/streams"
curl -H "$VIEWER_AUTH" "$BASE/api/v1/recordings?stream_id=uvc_cam1&limit=20"
```
