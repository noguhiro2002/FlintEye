<a id="advanced-reference-media-operations"></a>
# 高度なリファレンス: メディア操作

[English](MEDIA_OPERATIONS.md)

[ドキュメント](../README.ja.md) · [手動インストール](../MANUAL_INSTALL.ja.md)

> これらはリポジトリのルートから実行する低レベルのソース/開発用コマンドです。
> パッケージ化されたアプリケーションについては、[ユーザーガイド](../USER_GUIDE.ja.md)を使用してください。
> MediaMTX単体の保持およびサービス設定は、FlintEyeが管理するストレージには適用されません。
> リスナーはループバックに維持してください。LANアクセスには、[配布ガイド](../DISTRIBUTION.ja.md)で説明されている認証済みHTTPSプロキシを使用します。

<a id="8-multi-cam-view-ffmpeg-compose"></a>
## 8. マルチカムビュー (FFmpeg合成)

MediaMTXに既にパブリッシュされているUVCおよびIPカメラのストリームを、1つ以上のタイル表示に合成します。

実行:

```powershell
python -m flinteye_app.workers.multiview_to_rtsp --env-file ".env"
```

主要な `.env` フィールド:

- `MV_SOURCE_MODE=hybrid|env|api`
- `MV_SOURCE_PATHS=uvc_cam1,uvc_cam2,ipcam1,...`
- `MV_AUTO_PLACEHOLDER_MISSING_SOURCES=true|false`
- `MV_MTX_API_URL=http://127.0.0.1:9997/v3/paths/list`
- `MV_INPUT_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MV_OUTPUT_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MV_OUTPUT_PREFIX=multiview`
- `MV_TILE_COUNT=4` (2..32)
- `MV_CANVAS_WIDTH`, `MV_CANVAS_HEIGHT`, `MV_GRID_COLUMNS`
- `MV_SLOT_POSITIONS` およびオプションのビューごとの `MV_VIEW_1_SLOT_POSITIONS`
- `MV_FPS`, `MV_LATENCY_PRESET=low|normal`, `MV_QUALITY_PRESET`, `MV_BITRATE`, `MV_MAXRATE`, `MV_BUFSIZE`, `MV_GOP`, `MV_BFRAMES`
- `MV_INPUT_STALL_TIMEOUT_SEC=15` (RTSP入力ストールタイムアウトを無効にするには `0` を設定)
- `MV_INPUT_STALL_TIMEOUT_OPTION=auto|rw_timeout|stimeout|timeout|none`
- `MV_MAINTENANCE_ENABLED=true|false`
- `MV_MAINTENANCE_RESTART_INTERVAL_SEC=43200`
- `MV_MAINTENANCE_ALIGN_WITH_RECORD_SEGMENTS=true|false`
- `MV_MAINTENANCE_RESTART_OFFSET_SEC=2`

分割の動作:

- スクリプトは、それぞれ `MV_TILE_COUNT` 個のストリームからなるページを作成します。
- カメラの総数がタイル数で割り切れない場合、最後のビューは部分的に埋められます。
- 例: カメラ `10` 台、`MV_TILE_COUNT=4` の場合 -> `multiview_1` (4)、`multiview_2` (4)、`multiview_3` (2)。

ループ防止:

- `MV_OUTPUT_PREFIX` または `MV_OUTPUT_PREFIX_*` に一致するソースパスは、自動的に除外されます。
- これにより、マルチビューの出力を入力として再取り込みすることを防ぎます。

運用上の推奨事項:

- オーケストレーターを通じたイベント駆動型の再起動を有効に維持します (カメラの再起動 -> マルチビューの再起動)。
- 定期的なマルチビューのメンテナンス再起動も有効にしてください。
- 推奨されるデフォルト: 録画セグメントの境界に合わせ、境界の後に `2s` のオフセットを挟んで、`12h` ごとに再起動します。

<a id="81-multiview-stutter--freeze-troubleshooting"></a>
### 8.1 マルチビューのカクつき / フリーズのトラブルシューティング

症状:

- 1つのタイルが数秒間停止し、その後ジャンプするように進む。
- マルチビューの出力全体がカクカクする、または「カクカク」になる。
- 単一カメラのライブビューでは正常に見える同じカメラが、マルチビュー内でのみカクつく。

最も一般的な原因:

- `MV_LATENCY_PRESET=low` がソースの安定性に対してアグレッシブすぎます。バッファリングを最小限に抑えますが、タイムスタンプの不安定さや短いネットワークのストールが、フリーズやスキップとして目に見えるようになります。
- IPカメラが `MTX_IP_<TOKEN>_RELAY_MODE=copy` を使用しているため、上流のGOP/タイムスタンプの不規則性がそのままマルチビューに伝播します。
- 現在の `MV_FPS`、タイル数、および総ビットレートに対して、エンコーダーまたはCPUの負荷が高すぎます。

問題を切り分ける方法:

1. 単一カメラのストリームはスムーズだがマルチビューのみがカクつく場合は、まずマルチビューの合成設定を疑ってください。
2. 単一カメラのストリームがすでに不安定な場合は、まずソースパブリッシャーを修正してください (`flinteye_app/workers/uvc_to_rtsp.py` またはIPリレーパス)。
3. 他が継続しているのに1つのタイルがフリーズする場合は、その特定のソースパスを疑ってください。
4. すべてのタイルが同時にフリーズする場合は、マルチビューのフレーム同期 / エンコーダー / 出力パスを疑ってください。

推奨される緩和策の順序:

1. 設定で、`3s` の遅延、`5s` の容量、および `10fps` を指定して **Raw wall-clock compositor (生ウォールクロックコンポジター)** を有効にします。
2. 同期合成が有効な場合、デフォルトの入力として **Primary** を使用します。各ソースはすでに生のリングに個別にデコードされています。`normalized_primary` は冗長なエンコード/内部RTSP/デコードステージを追加します。
3. 入力ごとの `64 MB` と最大保持の `10s` を初期値として維持します。
4. 同期バッファリングが無効な場合は、`MV_LATENCY_PRESET=normal` を変更し、`MV_FPS` を下げます。
5. マルチビュー外の不安定なソースタイムスタンプには、メインリレーのウォールクロックモードを使用します。公開されている個々のカメラのパスは、マルチビューの設定によって変更されません。

Raw wall-clock compositorの動作:

- 選択されたすべての入力には、独立したFFmpegデコーダーと、メモリ内の境界付きRGBフレームリングがあります。
- フレームにはFlintEyeホストクロックのタイムスタンプが付けられます。1つのワーカーが、すべてのタイルについて `now - delay_sec` 時点またはそれ以前の最新のフレームを選択し、それらのフレームを1つのキャンバスにコピーします。
- 最終的なビューごとに1つのFFmpegエンコーダーが、完成した生キャンバスのみを受信して `multiview_*` をパブリッシュします。中間的な `__mv_buffer/*` H.264パブリッシャー、RTSPリーダー、2回目のデコード、または `xstack` プロセスはありません。
- 1つの入力が切断された場合、そのデコーダーのみが再接続します。そのタイルは最大 `max_hold_sec` まで最後のフレームを保持し、その後、他のタイルと最終出力が継続する一方で黒画面になります。
- ステータスファイルは、フレームを選択および合成するのと同じワーカーによって書き込まれるため、ソースの健全性によって最終コンポジターの健全性が上書きされることはありません。
- 最終的な `multiview_*` 出力のみが録画されます。
- この機能は既存のランタイムファイルに対してオプトインです。有効化または変更すると、MediaMTXや公開カメラのリレーではなく、マルチビューワーカーのみが再起動します。

実践的なガイダンス:

- `copy` は効率的ですが、不安定なIPカメラに対して最も許容度の低いオプションです。
- `libx264` はCPUコストがかかりますが、通常、より安定したマルチビュー入力を生成します。
- 不安定なセットアップのトラブルシューティングを行う場合は、安定性を最優先してください: `MV_LATENCY_PRESET=normal`、短いGOP、および中程度のFPS。

確認すべき場所:

- `logs/multiview.log`
- `logs/<camera>.log`
- `GET /api/v1/status/processes`

一般的なログの手がかり:

- `404 Not Found`: マルチビューがオープンしようとしたときにソースパスの準備ができていませんでした。
- `Broken pipe`: 下流のRTSP出力またはコンシューマーが切断されました。
- タイムスタンプ / DTSの警告: タイムスタンプが不安定であり、低遅延設定がアグレッシブすぎる可能性があります。

ドライラン (FFmpegコマンドの出力のみ):

```powershell
python -m flinteye_app.workers.multiview_to_rtsp --env-file ".env" --dry-run
```


<a id="9-mediamtx-loop-recording"></a>
## 9. MediaMTXループ録画

このセットアップにより、複数のMediaMTXパス (UVCおよびIPカメラ) のループ録画が可能になります。
`flinteye_app/orchestrator_api.py` は、起動時に `.env` / `runtime.json` から `mediamtx.yml` に録画設定を直接適用できるようになりました (デフォルトで有効)。
`tools/setup_mediamtx_recording.ps1` は、スタンドアロン/手動のWindowsサービスワークフローにおいて引き続き有用です。

<a id="91-configure-recording-automated"></a>
### 9.1 録画の設定 (自動化)

推奨される起動順序:

1. カメラストリームをパブリッシュする (`flinteye_app/workers/uvc_to_rtsp.py` および/またはMediaMTX IPカメラソース)
2. `flinteye_app/workers/multiview_to_rtsp.py` を起動して `multiview_*` パスをパブリッシュする
3. `tools/setup_mediamtx_recording.ps1` で録画設定を適用する

PowerShellを管理者として実行:

```powershell
cd C:\path\to\FlintEye
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env"
```

CLIから直接録画パスをオーバーライドする (オプション):

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordPaths "uvc_cam1","uvc_cam2","ipcam1","ipcam2"
```

このスクリプトの動作:

- バックアップを作成: `mediamtx.yml.bak` (`mediamtx.yml` と同じディレクトリ)
- `MTX_RECORD_PATHS` (または `-RecordPaths`) 内の各パスの下に録画設定を追加/更新する
- オプションで `multiview_1..multiview_N` 録画ターゲットを自動的に含める
- オプションで `MTX_IP_PATHS` 内の各パスにIPカメラ `source` を追加/更新する
- `C:/recordings/mediamtx` を作成する
- 現在のユーザー (または `-MediaMTXUser`) に変更権限を付与する
- MediaMTXサービスを再起動する (指定しない限り `-NoRestart`)

関連する `.env` キー:

- `MTX_CONFIG_PATH` ( `-ConfigPath` が渡されない場合は必須)
- `MTX_RECORD_AUTO_APPLY` (デフォルト `true`; オーケストレーターから `mediamtx.yml` を自動パッチ)
- `MTX_RECORD_ROOT`
- `MTX_RECORD_FORMAT` (デフォルト `fmp4`)
- `MTX_RECORD_PART_DURATION` (デフォルト `1s`)
- `MTX_RECORD_MAX_PART_SIZE` (デフォルト `50M`)
- `MTX_RECORD_SEGMENT_DURATION`
- `MTX_RECORD_DELETE_AFTER`
- `PLAYBACK_CACHE_DELETE_AFTER` (デフォルト `24h`; 内部での再生しやすいMP4ファイルの保持期間)
- `MTX_RECORD_PATHS` (例: `uvc_cam1,uvc_cam2,ipcam1,ipcam2`)
- `MTX_RECORD_INCLUDE_MULTIVIEW` (デフォルト `true`)
- `MTX_MULTI_VIEW_PREFIX` (デフォルト `multiview`)
- `MTX_MULTI_VIEW_MAX_COUNT` (デフォルト `16`)
- `MTX_IP_PATHS` (オプション)
- `MTX_IP_<TOKEN>_SOURCE` (オプション; 例: `MTX_IP_IPCAM1_SOURCE`)
- `MTX_IP_<TOKEN>_RELAY_MODE` (`copy` または `libx264`; デフォルト `copy`)
- `MTX_IP_<TOKEN>_BITRATE` (オプション; `RELAY_MODE=libx264` のとき使用)
- `MTX_IP_<TOKEN>_MAXRATE` (オプション; `RELAY_MODE=libx264` のとき使用)
- `MTX_IP_<TOKEN>_BUFSIZE` (オプション; `RELAY_MODE=libx264` のとき使用)
- `MTX_IP_<TOKEN>_GOP` (デフォルト `40`)
- `MTX_IP_<TOKEN>_X264_PRESET` (デフォルト `veryfast`)
- `MTX_SERVICE_NAME`
- `MTX_SERVICE_USER`

<a id="92-recording-settings-applied-to-each-recording-path"></a>
### 9.2 各録画パスに適用される録画設定

```yaml
paths:
  uvc_cam1:
    record: yes
    recordPath: C:/recordings/mediamtx/%path/%Y-%m-%d/%H-%M-%S-%f
    recordFormat: fmp4
    recordPartDuration: 1s
    recordMaxPartSize: 50M
    recordSegmentDuration: 10m
    recordDeleteAfter: 168h

  ipcam1:
    source: rtsp://username:password@192.168.1.101:554/stream1
    record: yes
    recordPath: C:/recordings/mediamtx/%path/%Y-%m-%d/%H-%M-%S-%f
    recordFormat: fmp4
    recordPartDuration: 1s
    recordMaxPartSize: 50M
    recordSegmentDuration: 10m
    recordDeleteAfter: 168h
```

<a id="93-validate-functionality"></a>
### 9.3 機能の検証

ストリーム開始後、ファイルが作成されていることを確認します:

```powershell
Get-ChildItem "C:\recordings\mediamtx" -Recurse
```

セグメントのローテーションを確認します (約10分ごと):

```powershell
Get-ChildItem "C:\recordings\mediamtx" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName, LastWriteTime
```

<a id="94-short-retention-test-before-production"></a>
### 9.4 短期保持テスト (本番稼働前)

一時的な30分の保持期間を適用します:

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordDeleteAfter "30m"
```

削除動作が確認されたら、7日間の保持期間を復元します:

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordDeleteAfter "168h"
```

<a id="95-capacity-planning-and-24h-monitoring"></a>
### 9.5 キャパシティプランニングと24時間モニタリング

サイジングの基準 (ストリームごと):

- `2Mbps` -> 約 `21.6GB/day`
- `2Mbps` と `7 days` の保持期間 -> 約 `151GB`

簡易サイズ確認:

```powershell
$bytes = (Get-ChildItem "C:\recordings\mediamtx" -Recurse -File | Measure-Object Length -Sum).Sum
"{0:N2} GB" -f ($bytes / 1GB)
```

ディスク空き容量の確認:

```powershell
Get-PSDrive C
```

運用ポリシー:

- 空き容量を `20%` より上に維持する
- 制限に近づいた場合は、ビットレートを下げる (`--quality-preset low`) または保持期間を短縮する


<a id="10-time-sync-check-ntp-before-latency-measurement"></a>
## 10. 遅延測定前の時刻同期確認 (NTP)

送信側と受信側のクロックが同期していない場合、測定された「遅延」が実際の転送遅延よりもはるかに大きく見えることがあります。

<a id="windows-recommended-check"></a>
### Windows (推奨される確認方法)

現在の同期状態を確認:

```powershell
w32tm /query /status
w32tm /query /source
Get-Date
```

クロックの再同期 (PowerShellを管理者として実行):

```powershell
w32tm /resync
```

再同期に失敗した場合は、Windows Timeサービスを再起動して再試行してください:

```powershell
Restart-Service w32time
w32tm /resync
```

<a id="linux"></a>
### Linux

```bash
timedatectl status
sudo timedatectl set-ntp true
```

<a id="macos"></a>
### macOS

```bash
sudo systemsetup -setusingnetworktime on
sudo sntp -sS time.apple.com
```

<a id="automatic-latency-measurement-ocr-based"></a>
### 自動遅延測定 (OCRベース)

ストリームのオーバーレイに送信時刻が `YYYY/MM/DD hh:mm:ss` で含まれている場合、遅延を自動的に推定できます。

要件:

- `ffmpeg`
- `tesseract` OCR

インストールの例 (macOS):

```bash
brew install tesseract
```

カメラストリームの遅延を測定:

```bash
python3 -m tools.measure_rtsp_latency \
  --rtsp-url rtsp://127.0.0.1:8554/uvc_cam1 \
  --samples 20 \
  --interval 0.5
```

マルチビューの遅延を測定:

```bash
python3 -m tools.measure_rtsp_latency \
  --rtsp-url rtsp://127.0.0.1:8554/multiview_1 \
  --samples 20 \
  --interval 0.5
```

タイル状のマルチビューの場合は、各タイルのタイムスタンプ領域をターゲットにするように `--crop w:h:x:y` を調整します。

注意事項:

- オーバーレイの時刻は秒単位であるため、測定分解能は約 `+/-1s` です。
- テストの前に、送信側と受信側でNTP同期を実行してください。
