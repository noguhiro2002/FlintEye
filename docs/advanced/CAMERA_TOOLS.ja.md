<a id="advanced-reference-camera-tools"></a>

# 詳細リファレンス: カメラツール

[English](CAMERA_TOOLS.md)

[ドキュメント](../README.ja.md) · [手動インストール](../MANUAL_INSTALL.ja.md)

> これらはリポジトリルートから実行する低レベルのソース／開発用コマンドです。
> パッケージ版アプリケーションについては、[ユーザーガイド](../USER_GUIDE.ja.md)を参照してください。
> 単体 MediaMTX の保持期間およびサービス設定は、FlintEye 管理下のストレージには適用されません。
> リスナーはループバックに維持してください。LAN アクセスには、[配布ガイド](../DISTRIBUTION.ja.md)で説明されている認証付き HTTPS プロキシを使用します。

<a id="1-prerequisites"></a>

## 1. 前提条件

- Python 3.13+
- `ffmpeg` がインストールされていること
- MediaMTX の RTSP エンドポイントがすでに準備されていること（ご指定のとおり）

`ffmpeg` の確認:

```bash
ffmpeg -version
```

`drawtext` が利用可能か確認:

```bash
ffmpeg -hide_banner -filters | grep drawtext
```

`drawtext` がない場合は、`libfreetype` を有効にして ffmpeg をインストール／ビルドしてください。

<a id="2-script-location"></a>

## 2. スクリプトの場所

`flinteye_app/workers/uvc_to_rtsp.py`
`flinteye_app/workers/multiview_to_rtsp.py`

以下の例では、シェルがリポジトリのルートディレクトリにあることを前提としています。

実行:

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp --help
python3 -m flinteye_app.workers.multiview_to_rtsp --help
```

<a id="recommended-env-based-parameter-management"></a>

### 推奨: `.env` ベースのパラメータ管理

テンプレートから実行時設定を作成します:

```bash
# macOS
cp config/examples/.env.example.mac .env

# Linux
# cp config/examples/.env.example.linux .env

# Windows PowerShell
# Copy-Item config/examples/.env.example.windows .env
```

`.env` の値を編集し、最小限の引数で実行します:

```powershell
python -m flinteye_app.workers.uvc_to_rtsp
```

マルチ UVC 構成では、プロファイルベースのキーを使用します:

- 共有デフォルト: `UVC_*`
- カメラごとの上書き: `UVC_<PROFILE>_*`（例: `UVC_CAM1_*`、`UVC_CAM2_*`）

各カメラを個別のプロセスで実行します:

```powershell
python -m flinteye_app.workers.uvc_to_rtsp --profile cam1
python -m flinteye_app.workers.uvc_to_rtsp --profile cam2
```

便利なスイッチ:

- `--env-file path/to/file.env`: 特定の env ファイルを使用
- `--no-env`: `.env` を無視し、CLI／デフォルトのみを使用
- `--profile cam1`: 最初に `UVC_CAM1_*` を読み込み、その後 `UVC_*` にフォールバック

優先順位:

- CLI 引数 > `.env` > 組み込みデフォルト

<a id="3-linux-v4l2"></a>

## 3. Linux (v4l2)

<a id="find-camera-device"></a>

### カメラデバイスの検索

```bash
ls /dev/video*
```

オプション（`v4l2-ctl` がインストールされている場合）:

```bash
v4l2-ctl --list-devices
```

<a id="run"></a>

### 実行

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --input-driver v4l2 \
  --device /dev/video0 \
  --camera-name "CAM-LINUX-01" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" \
  --width 1280 \
  --height 720 \
  --fps 30 \
  --input-format mjpeg
```

<a id="4-macos-avfoundation"></a>

## 4. macOS (avfoundation)

<a id="list-camera-devices"></a>

### カメラデバイスの一覧表示

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

インデックス形式（例: `0:none`）またはデバイス名形式（例: `FaceTime HD Camera:none`）のいずれかを使用します。

<a id="run-1"></a>

### 実行

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --input-driver avfoundation \
  --device "0:none" \
  --camera-name "CAM-MAC-01" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" \
  --width 1280 \
  --height 720 \
  --fps 30
```

<a id="5-windows-dshow"></a>

## 5. Windows (dshow)

<a id="list-camera-devices-1"></a>

### カメラデバイスの一覧表示

```powershell
ffmpeg -list_devices true -f dshow -i dummy
```

出力に表示されたデバイス名を使用します。

<a id="run-2"></a>

### 実行

```powershell
python -m flinteye_app.workers.uvc_to_rtsp `
  --input-driver dshow `
  --device "Integrated Camera" `
  --camera-name "CAM-WIN-01" `
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" `
  --fontfile "C:/Windows/Fonts/arial.ttf" `
  --rtbufsize 256M `
  --width 1280 `
  --height 720 `
  --fps 30
```

dshow に関する注意:

- `--device "video=Integrated Camera"` のように明示的に指定できます。
- `video=` を省略した場合、スクリプトが自動的に追加します。
- ffmpeg が `Fontconfig` エラーを出力する場合は、`--fontfile` を明示的に設定してください。
- Windows では、ドライブ文字を含む `--fontfile` は内部で正規化されます（例: `C:/Windows/Fonts/arial.ttf` -> `/Windows/Fonts/arial.ttf`）。

<a id="6-useful-options"></a>

## 6. 便利なオプション

- `--env-file PATH`: env ファイルから実行時設定を読み込む（デフォルト `.env`）
- `--no-env`: env ファイルの値を無視する
- `--profile NAME`: プロファイル固有の env キー（`UVC_<NAME>_*`）を使用する
- `--encoder auto`（デフォルト）: 利用可能な H.264 エンコーダーを自動的に選択する
- `--latency-preset low`: 低遅延チューニングを適用する（小さいバッファと低遅延フラグ）
- `--quality-preset high|standard|low`: ビットレートプリセットを適用する（`high=4M`、`standard=2M`、`low=1M`）
- `--encoder libx264`: ソフトウェアエンコードを強制する
- `--font-size 28`: オーバーレイテキストのサイズを変更する
- `--fontfile /path/to/font.ttf`: フォントファイルを明示的に指定する
- `--rtbufsize 256M`: リアルタイム入力バッファを増やす（dshow に有効）
- `--bframes 0`: B フレームを無効のままにする（MediaMTX WebRTC に必要）
- `--dry-run`: 生成された ffmpeg コマンドを出力して終了する

`--encoder auto` を使用すると、スクリプトはプラットフォーム固有のハードウェアエンコーダーを試し、自動的にフォールバックします。

- Windows の順序: `h264_qsv` -> `h264_amf` -> `h264_nvenc` -> `libx264`
- macOS の順序: `h264_videotoolbox` -> `libx264`
- Linux の順序: `h264_v4l2m2m` -> `h264_nvenc` -> `h264_qsv` -> `h264_amf` -> `libx264`

プリセットの目安:

- `high`: `bitrate=4M`、`maxrate=4M`、`bufsize=8M`（1080p の推奨開始点）
- `standard`: `bitrate=2M`、`maxrate=2M`、`bufsize=4M`（720p の推奨開始点）
- `low`: `bitrate=1M`、`maxrate=1M`、`bufsize=2M`（帯域節約プロファイル）
- 手動オプション（`--bitrate`、`--maxrate`、`--bufsize`）はプリセット値を上書きします。

遅延の目安:

- `--latency-preset low` はデフォルト値（`thread_queue_size`、`gop`、`rtbufsize`）を減らし、低遅延 ffmpeg フラグを有効にします。
- `low` モードでは、キューによる遅延の増大を抑えるため、`thread_queue_size` が `32` に削減されます。
- `low` モードでは、ウォールクロックタイムスタンプと `genpts` が有効になり、RTSP mux 遅延が `0` に強制されます。
- これにより遅延を減らせますが、バッファが小さすぎると低速なマシンでフレームドロップが増える可能性があります。

ドライランの例:

```bash
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-TEST" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam01" \
  --dry-run
```

プリセットの例:

```bash
# 1080p / high quality
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-HIGH" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam_high" \
  --width 1920 --height 1080 \
  --quality-preset high
```

```bash
# 720p / standard quality
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-STD" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam_std" \
  --width 1280 --height 720 \
  --quality-preset standard
```

```bash
# 720p / standard quality + low latency
python3 -m flinteye_app.workers.uvc_to_rtsp \
  --camera-name "CAM-STD-LL" \
  --rtsp-url "rtsp://127.0.0.1:8554/cam_std_ll" \
  --width 1280 --height 720 \
  --quality-preset standard \
  --latency-preset low
```

<a id="7-troubleshooting"></a>

## 7. トラブルシューティング

- `drawtext` エラー: `libfreetype` サポート付きで ffmpeg をインストールしてください。
- `Fontconfig error: Cannot load default config file`（主に Windows）: `--fontfile "C:/Windows/Fonts/arial.ttf"` を指定してください。
- `Cannot load nvcuda.dll`: NVIDIA ランタイムが利用できません。`--encoder auto` のままにする（スクリプトが Intel/AMD/ソフトウェアエンコーダーを再試行します）か、`--encoder libx264` を設定してください。
- `dshow ... real-time buffer ... too full`: `--rtbufsize` を増やす（例: `--rtbufsize 512M`）か、`--fps`／解像度を下げてください。
- カメラが見つからない: お使いの OS セクションのデバイス一覧表示コマンドを再確認してください。
- 高遅延: `--gop`、解像度、またはビットレートを下げてください。
- Apple Silicon に関する注意（GPU 対 CPU）: 複数の UVC エンコーダーとマルチビューを同時に実行すると、`h264_videotoolbox` でタイムスタンプの不安定さ（`Non-monotonic DTS`）が発生し、ソフトウェアエンコードより遅くなる場合があります。その場合は、`UVC_ENCODER=libx264` と `MV_ENCODER=libx264`（および必要に応じて `UVC_LATENCY_PRESET=normal`、`MV_LATENCY_PRESET=normal`）を設定すると、より安定した低遅延動作が得られます。ソフトウェアエンコード使用時は CPU 使用率を監視してください。
- RTSP トランスポートは TCP のままにしてください（スクリプトですでに設定済みです）。
- Live View サムネイルに関する注意: UI はすでに各カメラに対して API スナップショットエンドポイント（`GET /api/v1/cameras/{camera_id}/snapshot`）を使用しています。手動で 1 つずつ API を呼び出す方が安定して見えるのは、同時スナップショット負荷が減るためです。
- `/snapshot` または Live View サムネイルが散発的に失敗する場合は、まず `SNAPSHOT_TIMEOUT_SEC` を増やしてください（例: `3.0` -> `8.0`）。スナップショットのキャプチャはデコード可能なフレームを待機するため、長い GOP／遅いキーフレーム／不安定な IP カメラではタイムアウトを超えることがあります。
