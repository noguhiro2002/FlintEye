<a id="advanced-reference-media-operations"></a>

# 上級リファレンス: メディア運用

[English](MEDIA_OPERATIONS.md)

[ドキュメント](../README.ja.md) · [手動インストール](../MANUAL_INSTALL.ja.md)

> これらはリポジトリのルートから実行する低レベルのソース/開発用コマンドです。
> パッケージ版のアプリケーションについては、[ユーザーガイド](../USER_GUIDE.ja.md)を参照してください。
> 単体MediaMTXの保持期間およびサービス設定は、FlintEyeが管理するストレージには適用されません。
> リスナーはループバックに維持してください。LANアクセスには[配信ガイド](../DISTRIBUTION.ja.md)で説明されている認証付きHTTPSプロキシを使用します。

<a id="8-multi-cam-view-ffmpeg-compose"></a>

## 8. マルチカメラビュー (FFmpeg Compose)

MediaMTXですでに配信されているUVCおよびIPカメラのストリームを、1つ以上のタイル表示ビューに合成します。

実行:

```powershell
python -m flinteye_app.workers.multiview_to_rtsp --env-file ".env"
```

主な`.env`フィールド:

- `MV_SOURCE_MODE=hybrid|env|api`
- `MV_SOURCE_PATHS=uvc_cam1,uvc_cam2,ipcam1,...`
- `MV_AUTO_PLACEHOLDER_MISSING_SOURCES=true|false`
- `MV_MTX_API_URL=http://127.0.0.1:9997/v3/paths/list`
- `MV_INPUT_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MV_OUTPUT_RTSP_BASE_URL=rtsp://127.0.0.1:8554`
- `MV_OUTPUT_PREFIX=multiview`
- `MV_TILE_COUNT=4` (2..32)
- `MV_CANVAS_WIDTH`、`MV_CANVAS_HEIGHT`、`MV_GRID_COLUMNS`
- `MV_SLOT_POSITIONS` およびオプションのビュー別 `MV_VIEW_1_SLOT_POSITIONS`
- `MV_FPS`、`MV_LATENCY_PRESET=low|normal`、`MV_QUALITY_PRESET`、`MV_BITRATE`、`MV_MAXRATE`、`MV_BUFSIZE`、`MV_GOP`、`MV_BFRAMES`
- `MV_INPUT_STALL_TIMEOUT_SEC=15` (RTSP入力ストールタイムアウトを無効にするには `0` を設定)
- `MV_INPUT_STALL_TIMEOUT_OPTION=auto|rw_timeout|stimeout|timeout|none`
- `MV_MAINTENANCE_ENABLED=true|false`
- `MV_MAINTENANCE_RESTART_INTERVAL_SEC=43200`
- `MV_MAINTENANCE_ALIGN_WITH_RECORD_SEGMENTS=true|false`
- `MV_MAINTENANCE_RESTART_OFFSET_SEC=2`

分割動作:

- スクリプトはそれぞれ `MV_TILE_COUNT` 個のストリームからなるページを作成します。
- カメラの総数がタイル数で割り切れない場合、最後のビューは部分的に埋められます。
- 例: `10` 台のカメラで `MV_TILE_COUNT=4` の場合 -> `multiview_1` (4)、`multiview_2` (4)、`multiview_3` (2)。

ループ防止:

- `MV_OUTPUT_PREFIX` または `MV_OUTPUT_PREFIX_*` に一致するソースパスは自動的に除外されます。
- これにより、マルチビュー出力を入力として再取り込みすることを防ぎます。

運用上の推奨事項:

- オーケストレーターによるイベント駆動型の再起動を有効にしておきます（カメラ再起動 -> マルチビュー再起動）。
- また、定期的なマルチビューのメンテナンス再起動も有効にしてください。
- 推奨デフォルト: `12h` ごとに再起動し、録画セグメント境界に合わせ、境界から `2s` のオフセットを設けます。

<a id="81-multiview-stutter--freeze-troubleshooting"></a>

### 8.1 マルチビューのカクつき / フリーズのトラブルシューティング

症状:

- 1つのタイルが数秒間停止し、その後前方にジャンプする。
- マルチビュー出力全体が途切れ途切れになったり、「カクカク」したりする。
- 単一カメラのLive View（ライブビュー）では正常に見えるカメラがあるが、その同じカメラがマルチビュー内でのみカクつく。

最も一般的な原因:

- `MV_LATENCY_PRESET=low` がソースの安定性に対してアグレッシブすぎる。バッファリングは最小限に抑えられますが、不安定なタイムスタンプや一時的なネットワークのストールがフリーズやスキップとして目に見えるようになります。
- IPカメラが `MTX_IP_<TOKEN>_RELAY_MODE=copy` を使用しているため、アップストリームのGOP/タイムスタンプの不規則性がマルチビューに直接パススルーされている。
- 現在の `MV_FPS`、タイル数、合計ビットレートに対して、エンコーダーまたはCPUの負荷が高すぎる。

問題の切り分け方法:

1. 単一カメラのストリームがスムーズで、マルチビューのみがカクつく場合は、まずマルチビューの合成設定を疑ってください。
2. 単一カメラのストリームがすでに不安定な場合は、まずソース配信元（`flinteye_app/workers/uvc_to_rtsp.py` またはIP中継パス）を修正してください。
3. 他のタイルが継続している間に1つのタイルのみがフリーズする場合は、その特定のソースパスを疑ってください。
4. すべてのタイルが一緒にフリーズする場合は、マルチビューのフレーム同期 / エンコーダー / 出力パスを疑ってください。

推奨される緩和手順:

1. Settings（設定）で、**Raw wall-clock compositor**（Raw実時間コンポジター）を遅延 `3s`、容量 `5s`、`10fps` で有効にします。
2. 同期合成が有効な場合、デフォルトの入力として **Primary**（プライマリ）を使用します。各ソースはすでに独立して独自のrawリングにデコードされます。`normalized_primary` は冗長なエンコード/内部RTSP/デコードの段階を追加してしまいます。
3. 初期値として入力ごとに `64 MB`、最大保持時間として `10s` を維持します。
4. 同期バッファリングが無効な場合は、`MV_LATENCY_PRESET=normal` に変更し、`MV_FPS` を下げます。
5. Multiview外でソースのタイムスタンプが不安定な場合は、メインリレーの実時間モードを使用してください。個別の公開カメラパスはMultiview設定によって変更されません。

Raw実時間コンポジターの動作:

- 選択されたすべての入力には、独立したFFmpegデコーダーと制限付きのインメモリRGBフレームリングがあります。
- フレームにはオーケストレーターのホストクロックによるタイムスタンプが付与されます。1つのワーカーがすべてのタイルに対して `now - delay_sec` 以前の最新フレームを選択し、それらのフレームを1つのキャンバスにコピーします。
- 最終ビューごとに1つのFFmpegエンコーダーが完成したrawキャンバスのみを受け取り、`multiview_*` を配信します。中間的な `__mv_buffer/*` H.264配信元、RTSPリーダー、2回目のデコード、または `xstack` プロセスは存在しません。
- 1つの入力が切断された場合、そのデコーダーのみが再接続します。そのタイルは最大 `max_hold_sec` まで最後のフレームを保持し、その後黒画面になりますが、他のタイルと最終出力は継続します。
- ステータスファイルはフレームを選択および合成する同じワーカーによって書き込まれるため、ソースの健全性によって最終コンポジターの健全性が上書きされることはありません。
- 最終的な `multiview_*` 出力のみが録画されます。
- この機能は既存のランタイムファイルに対してオプトインです。有効化または変更しても、再起動されるのはMultiviewワーカーのみであり、MediaMTXや公開カメラリレーは再起動されません。

実践的なガイダンス:

- `copy` は効率的ですが、不安定なIPカメラに対して最も許容度が低いオプションです。
- `libx264` はCPUコストが高くなりますが、通常はより安定したマルチビュー入力を生成します。
- 不安定なセットアップのトラブルシューティングを行う場合は、まず安定性を優先してください: `MV_LATENCY_PRESET=normal`、短いGOP、および控えめなFPS。

確認先:

- `logs/multiview.log`
- `logs/<camera>.log`
- `GET /api/v1/status/processes`

典型的なログの手がかり:

- `404 Not Found`: マルチビューがオープンしようとしたときにソースパスの準備ができていなかった。
- `Broken pipe`: ダウンストリームのRTSP出力またはコンシューマーが切断された。
- タイムスタンプ / DTS の警告: タイムスタンプが不安定であり、低遅延設定がアグレッシブすぎる可能性があります。

ドライラン (FFmpegコマンドの出力のみ):

```powershell
python -m flinteye_app.workers.multiview_to_rtsp --env-file ".env" --dry-run
```

<a id="9-mediamtx-loop-recording"></a>

## 9. MediaMTX ループ録画

このセットアップにより、複数のMediaMTXパス（UVCおよびIPカメラ）に対するループ録画が有効になります。
`flinteye_app/orchestrator_api.py` は、起動時に `.env` / `runtime.json` の録画設定を `mediamtx.yml` に直接適用できるようになりました（デフォルトで有効）。
`tools/setup_mediamtx_recording.ps1` は、スタンドアロン/手動のWindowsサービスワークフローにおいて引き続き有用です。

<a id="91-configure-recording-automated"></a>

### 9.1 録画の設定 (自動化)

推奨される起動順序:

1. カメラストリームを配信する (`flinteye_app/workers/uvc_to_rtsp.py` および/または MediaMTX IPカメラソース)
2. `flinteye_app/workers/multiview_to_rtsp.py` を起動して `multiview_*` パスを配信する
3. `tools/setup_mediamtx_recording.ps1` で録画設定を適用する

PowerShellを管理者として実行:

```powershell
cd C:\path\to\FlintEye
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env"
```

CLIから録画パスを直接オーバーライドする (オプション):

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordPaths "uvc_cam1","uvc_cam2","ipcam1","ipcam2"
```

このスクリプトが行うこと:

- バックアップの作成: `mediamtx.yml.bak` (`mediamtx.yml` と同じディレクトリ)
- `MTX_RECORD_PATHS` (または `-RecordPaths`) 内の各パスの下にある録画設定を追加/更新
- オプションで `multiview_1..multiview_N` の録画対象を自動的に含める
- オプションで `MTX_IP_PATHS` 内の各パスに対するIPカメラの `source` を追加/更新
- `C:/recordings/mediamtx` を作成
- 現在のユーザー (または `-MediaMTXUser`) に変更権限を付与
- MediaMTXサービスを再起動 (`-NoRestart` が指定されていない限り)

関連する`.env`キー:

- `MTX_CONFIG_PATH` (`-ConfigPath` が渡されない場合は必須)
- `MTX_RECORD_AUTO_APPLY` (デフォルト `true`。オーケストレーターから `mediamtx.yml` を自動パッチ)
- `MTX_RECORD_ROOT`
- `MTX_RECORD_FORMAT` (デフォルト `fmp4`)
- `MTX_RECORD_PART_DURATION` (デフォルト `1s`)
- `MTX_RECORD_MAX_PART_SIZE` (デフォルト `50M`)
- `MTX_RECORD_SEGMENT_DURATION`
- `MTX_RECORD_DELETE_AFTER`
- `PLAYBACK_CACHE_DELETE_AFTER` (デフォルト `24h`。内部再生用MP4ファイルの保持期間)
- `MTX_RECORD_PATHS` (例: `uvc_cam1,uvc_cam2,ipcam1,ipcam2`)
- `MTX_RECORD_INCLUDE_MULTIVIEW` (デフォルト `true`)
- `MTX_MULTI_VIEW_PREFIX` (デフォルト `multiview`)
- `MTX_MULTI_VIEW_MAX_COUNT` (デフォルト `16`)
- `MTX_IP_PATHS` (オプション)
- `MTX_IP_<TOKEN>_SOURCE` (オプション。例: `MTX_IP_IPCAM1_SOURCE`)
- `MTX_IP_<TOKEN>_RELAY_MODE` (`copy` または `libx264`。デフォルト `copy`)
- `MTX_IP_<TOKEN>_BITRATE` (オプション。`RELAY_MODE=libx264` 時に使用)
- `MTX_IP_<TOKEN>_MAXRATE` (オプション。`RELAY_MODE=libx264` 時に使用)
- `MTX_IP_<TOKEN>_BUFSIZE` (オプション。`RELAY_MODE=libx264` 時に使用)
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

セグメントローテーションを確認 (~約10分ごと):

```powershell
Get-ChildItem "C:\recordings\mediamtx" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName, LastWriteTime
```

<a id="94-short-retention-test-before-production"></a>

### 9.4 短期保持テスト (本番運用前)

一時的な30分間の保持を適用:

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordDeleteAfter "30m"
```

削除動作が確認されたら、7日間の保持に戻します:

```powershell
.\tools/setup_mediamtx_recording.ps1 -EnvFile ".env" -RecordDeleteAfter "168h"
```

<a id="95-capacity-planning-and-24h-monitoring"></a>

### 9.5 容量計画と24時間監視

サイジングの基準 (ストリームごと):

- `2Mbps` -> 約 `21.6GB/day`
- `2Mbps` かつ保持期間 `7 days` -> 約 `151GB`

サイズのクイック確認:

```powershell
$bytes = (Get-ChildItem "C:\recordings\mediamtx" -Recurse -File | Measure-Object Length -Sum).Sum
"{0:N2} GB" -f ($bytes / 1GB)
```

ディスク空き容量の確認:

```powershell
Get-PSDrive C
```

運用ポリシー:

- 空き容量は `20%` 以上を維持する
- 上限に近づいた場合は、ビットレートを下げる（`--quality-preset low`）か保持期間を短縮する

<a id="10-time-sync-check-ntp-before-latency-measurement"></a>

## 10. 遅延測定前の時刻同期確認 (NTP)

送信側と受信側のクロックが同期していない場合、測定された「遅延」は実際のトランスポート遅延よりもはるかに大きく見えることがあります。

<a id="windows-recommended-check"></a>

### Windows (推奨される確認手順)

現在の同期状態を確認:

```powershell
w32tm /query /status
w32tm /query /source
Get-Date
```

クロックを再同期 (PowerShellを管理者として実行):

```powershell
w32tm /resync
```

再同期が失敗した場合は、Windows Timeサービスを再起動して再試行してください:

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

ストリームのオーバーレイに送信側時刻が `YYYY/MM/DD hh:mm:ss` 形式で含まれている場合、遅延を自動的に推定できます。

要件:

- `ffmpeg`
- `tesseract` OCR

インストール例 (macOS):

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

タイル表示マルチビューの場合、各タイルのタイムスタンプ領域を対象とするよう `--crop w:h:x:y` を調整します。

注意:

- オーバーレイ時刻は秒単位であるため、測定分解能は約 `+/-1s` です。
- テストを行う前に、送信側と受信側でNTP同期を実行してください。
