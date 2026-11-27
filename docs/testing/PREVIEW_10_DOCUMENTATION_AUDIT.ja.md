# Preview 10 公開後の文章監査

2026-11-27 に、README、利用・導入ガイド、API リファレンス、検証・配布手順を監査しました。公開版のバージョンと導入 URL は Preview 10 にそろっています。一方、設定項目の移動前の案内、提供済み機能の「次期版」表記、古い検証件数、署名の説明に不整合がありました。日英の修正は `codex/preview10-docs-audit` の専用作業ツリーで準備しました。本文の修正は、この監査記録と同じコミットに含めています。

## 設定の場所と現在の機能説明をそろえました

| 対象 | 見つかった不整合 | 修正内容 |
| --- | --- | --- |
| [README](../../README.ja.md)、[画像の説明](../../images/README.md) | 1.1.3 で撮影した映像を「現在の開発ビルド」と説明。旧ツアーと現行画面の区別が不十分 | 撮影版・日付を明記し、Preview 10 の画像付きガイドを案内 |
| [ユーザーガイド](../USER_GUIDE.ja.md)、[配布ガイド](../DISTRIBUTION.ja.md) | Basic と Advanced の分離、イベント録画・API キーの移動が未反映 | 通常の操作は Basic、イベント録画・API キーは Advanced → Integrations & API と記載 |
| 更新・診断・入門案内 | 更新確認を Settings → General、入門案内を常設の上部ボタンと説明 | Information の現在の導線に統一。テーマの System・Light・Dark も追記 |
| [LAN 接続](../LAN_ACCESS.ja.md)、[音声](../USER_GUIDE.ja.md#カメラの音声)、[Docker](../DOCKER.ja.md) | LAN HTTPS、カメラ音声、外部プレーヤー、Docker Desktop を今後の機能として説明 | Preview 10 での利用手順に更新。既存プロキシを使う方法と組み込み HTTPS を区別 |
| [API 認証](../advanced/API.ja.md#114-authentication) | コマンド例の `$AUTH` などが未定義。通常のサインインと旧トークン方式が混在 | ローカル認証のログインと Cookie を使う例に修正。REST API キー、イベント用トークン、旧認証方式の用途を明記 |
| API の補足 | カメラ ID と配信パスを同一と説明。サブセクション番号も重複 | ID はカメラ一覧から取得するよう修正。番号を整理し、以前の見出しリンクを保持 |
| [監視](../MONITORING.ja.md)、[ローカル Mac ビルド](../LOCAL_MACOS_BUILD.ja.md) | 廃止された Quick settings や更新確認の旧位置へ案内。録画の日付をファイル更新時刻だけで説明 | Basic → Runtime & access、Information へ更新。録画時刻とファイル更新時刻の選択を説明 |
| [開発資料](../advanced/DEVELOPMENT.ja.md)、[環境変数](../advanced/ENV_OPTIONS.ja.md) | 現行プレーヤーを iframe と説明。旧 Basic/Advanced 構成や古い README の説明を参照 | 現在の WebRtcPlayer、設定カテゴリ、管理者セッションに更新。ランチャー設定とワーカー設定の範囲も明記 |
| [導入ガイド](../INSTALL.ja.md)、リリースノートのテンプレート | macOS を「未署名」と説明する一方、別の段落ではアドホック署名済みと記載 | Windows の発行元の署名なしと、macOS のアドホック署名・Developer ID 未対応を分けて説明 |
| 削除手順・Issue テンプレート | 現在の操作例に Preview 3 のイメージタグ、バグ報告の例に 1.1.2 が残存 | 削除例を Preview 10 に更新。バグ報告は Information に表示される完全な版番号を求める表記へ変更 |

## 最新の検証結果と履歴を分けました

[インストール検証](../INSTALLATION_QA.ja.md)と[既知の問題](../KNOWN_ISSUES.ja.md)には、Preview 5 の 24/32 件、公開経路 8/10 件が最新の結果として残っていました。以下の Preview 10 の記録を先頭に示し、以前の結果は対象版を明記して履歴に残しました。

| Preview 10 の検証 | 完了した項目 | 残る確認 |
| --- | --- | --- |
| [ビルド時の導入・削除・再導入](https://github.com/noguhiro2002/FlintEye/actions/runs/45609459603) | 36件中28件が全7段階に合格 | macOS の8件は導入・整合性・削除まで合格し、導入後の起動は OS の承認待ち |
| [公開 URL・GHCR からの導入](https://github.com/noguhiro2002/FlintEye/actions/runs/45624057667) | 14件中12件が全7段階に合格 | macOS の2件は OS の承認待ち |

実機の初回起動、別端末からの接続、長時間運転などの確認は引き続き未完了です。以前の候補版で行った実カメラ試験も、最終ビルドでの合格とは分けて記載しています。

[受け入れ手順](../ACCEPTANCE.ja.md)と[開発記録](../DEVELOPMENT_1_2_0.ja.md)には、「実機確認前の開発プレビューを配布できる」という現行方針と、「公開前に実機確認が必須」という旧記述が併存していました。安定版に必要な実機確認と、未完了項目を開示して配布する開発プレビューの条件をそろえました。診断 ZIP を未提供とする記述も更新しました。

開発者向けの導入・貢献ガイドは、[共通のプッシュ前検証](CI_ACCEPTANCE.md#run-the-same-distribution-checks-before-pushing)を案内するよう統一しました。Build release が対象ファイルの main への変更でも起動することを反映しています。

## 公開物とアプリ内に残る文章があります

| 残る箇所 | 状態と対応案 |
| --- | --- |
| GitHub の About | 「Public preview builds are being prepared」が残っています。公開プレビューとコンテナーを提供中である説明への更新が適切です |
| アプリ内 API access の補足 | `frontend/src/components/ApiAccess.tsx` にイベント用トークンの場所を「Settings → Recording → Event recordings」と案内する文字列が残っています。現在は Advanced → Integrations & API にあります。次のアプリ更新で修正する対象です |
| 公開済みの `documentation.zip` と Release 本文 | 公開時点の文書を収録しており、今回修正した旧説明を含みます。今回の文書修正は自動反映されません。Release 本文から main の更新済みガイドを案内する方法があります |

旧版の検証コミット、Preview 8 の指摘、Preview 10 の改修計画、以前の変更履歴は、その時点の記録として保持しています。リリースノートの `@TAG@` などは公開処理で置換するテンプレートです。ライセンス原文と第三者の通知は変更していません。

## 照合と検査の範囲

監査開始時の main は `234eea855b3fd6da79bcf409766d457d1ab9fefb` です。[公開版](https://github.com/noguhiro2002/FlintEye/releases/tag/v1.2.0-preview.10)のアプリケーションコミットは `6508296ff967bbb5505dc51936fe0c85d144a8c7`、公開処理のコミットは `3b7171957ac12a1ccd474e4a7b66ecc5803b2644` でした。公開メタデータ、配布マニフェスト、QA の記録、公開時の文書 ZIP と、現在の画面・認証・ワークフローの実装を照合しました。

追跡対象の Markdown 65ファイルを横断検索し、利用・導入・API・検証手順を中心に内容を確認しました。補助資料、Issue テンプレート、アプリ内の関連説明も確認しています。文書の変更に対し、次の検査が通りました。

- `python packaging/check_docs.py` でローカルリンク、見出し、画像参照を検査。
- シェルのコード例173ブロックを `bash -n` で構文検査。
- API 文書の日英合計92箇所の明示された HTTP メソッドとパスを、既存の API 契約と照合。
- 主な導入ガイドの公開配布 URL 4種類を、Preview 10 の43個の公開アセットと照合。
- 既存の `test_release_packaging.py` 31テストが合格。

この監査ではインストーラーの再実行や実機試験を行っていません。コマンドの構文・契約の一致と、端末上での実行結果は区別しています。
