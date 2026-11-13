# ai-status-watcher

AIサービスの障害を監視し、状態が変わったときだけ Discord へ通知するツール。
GitHub Actions で定期実行し、状態は `state.json` に保持する
（pokemon-goods-watcher と同じ型の構成）。

## 監視対象

| サービス | 方式 | 備考 |
|---|---|---|
| Claude | 公式 Statuspage API (`https://status.claude.com/api/v2/`) | コンポーネント単位（claude.ai / Claude Code / Claude Console / Claude API など）で状態を見て、全体レベルを判定 |
| Meta Muse | HTTP到達チェック (`https://muse.ai`) | 公式ステータスページがないため、応答コードで判定。2xx〜4xx は応答あり、5xx・タイムアウト・接続エラーは down |

レベルは `ok`（正常）/ `degraded`（性能低下）/ `outage`（障害）の3段階。
Claude はコンポーネントのいずれかが `partial_outage` / `major_outage` なら `outage`、
`degraded_performance` があれば `degraded`、それ以外は `ok` と判定する。

## 通知の仕様

- **状態が変わったときだけ**通知する。変化がないときは通知しない。
  - `ok` → `degraded` / `outage`：【障害発生】
  - `degraded` / `outage` → `ok`：【復旧】
  - `outage` → `degraded` は【一部復旧】、`degraded` → `outage` は【障害発生】として通知する。
- 通知文には、サービス名・変化内容・影響コンポーネント・公式ステータスページへの
  リンク・確認時刻（JST）が入る。
- **初回実行時は通知しない**。現状態を `state.json` に初期記録するだけ（誤報防止）。
- ステータス取得自体が失敗した場合（APIに届かない等）は、そのサービスを障害とは
  判定せず「取得失敗」として扱い、通知しない。`state.json` の `fetch_error` が
  `true` になるので、取得失敗が続いていることはそこから分かる。
  各実行の詳細は Actions のログにも残る。

## セットアップ

1. **Discord Webhook を作成する**
   通知先チャンネルの「チャンネル設定 → 連携サービス → ウェブフック」から
   Webhook を作成し、URL をコピーする。

2. **GitHub Secrets に登録する**（リポジトリ所有者が行う作業）
   このリポジトリの Settings → Secrets and variables → Actions で、
   名前 `DISCORD_WEBHOOK_URL`、値に Webhook URL を登録する。

3. **初回実行**
   登録後、Actions タブから `Check AI Service Status` を手動実行
   （Run workflow）すると、その時点の状態が初期記録される。
   以後は5分間隔の定期実行で監視が続く。

Webhook 未登録の間は dry-run 動作になり、送信はされず、
Actions のログに「送信予定の内容」が出力されるだけなので、
登録前に動作確認ができる。

## 運用上の注意

- **GitHub Actions のスケジュールは遅延することがある。**
  cron は `*/5 * * * *`（5分間隔）に設定しているが、GitHub 側の混雑により
  実際の実行は遅れたり、間隔が空いたりする場合がある。「正確に5分ごと」では
  ない点に注意。
- **長期間状態変化がないと `state.json` のコミットは発生しない。**
  確認時刻（`last_check`）だけの更新ではコミットしない設計のため、
  リポジトリが長期間静かに見えることがあるが、監視自体は Actions で
  回り続けている。動作を確かめたいときは Actions タブから手動実行できる。
  なお、GitHub の仕様で、リポジトリに長期間アクティビティがないと
  スケジュール実行が自動で無効化される場合がある。その場合も Actions タブから
  再有効化・手動実行ができる。

## 拡張方針（サービスの追加）

対象サービスは `config.yaml` で管理しているので、基本的にはエントリ追加で増やせる。

- Statuspage 形式のサービス（例: ChatGPT = `https://status.openai.com`）は
  `type: statuspage` で `status_url` / `components_url` / `page_url` を書けば
  そのまま監視対象になる。
- Gemini のように形式が異なるサービスは、`main.py` の `CHECKERS` に
  チェック関数を追加し、`type` で振り分ける。
- HTTP到達だけ見ればよいサービスは `type: http` で `check_url` を書く。

## ファイル構成

- `main.py` — 監視の本体（設定読み込み、状態判定、通知の組み立て）
- `notifier.py` — Discord Webhook 送信（未設定時は dry-run）
- `state.py` — `state.json` の読み書き
- `config.yaml` — 監視対象サービスの定義
- `state.json` — 前回状態の保持（Actions が自動コミットする）
- `.github/workflows/check.yml` — 5分間隔の定期実行ワークフロー
