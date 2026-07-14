# pe-runner

[Project Euler](https://projecteuler.net/) をみんなでコンテスト形式で解く Discord bot。マスコットは「オイラーにゃん」🐱。

参加者は一度 `/register` するだけ。コンテストごとにボタンで参加表明し、AC（正答）は bot が
Project Euler の progress ページを実際に読んで**検証**します。順位表・投票おすすめ・AtCoder 風の
コミュニティレーティングまで揃っています。

---

## 主な機能

- **コンテスト**：難易度タイプ（初心者/中級者/上級者）と開始時刻を指定して作成。参加者は
  ボタンで opt-in。開始前に**参加者が全員未ACの問題だけ**を自動抽選して出題。
- **AC 検証**：`/submit` すると、その人の PE friend-progress を再取得して**本当に解いたか確認**
  （自己申告ではない）。スコアは難易度%＝得点、同点は最終AC時刻で tiebreak。
- **順位表**：`参加者 × 各問題の AC 状況（✓/·）` を等幅テーブルで表示。提出のたび自動更新。
- **レーティング**：AtCoder 風（性能を recency 重み付き集約・参加時のみ変動＝不参加で下がらない）
  ＋非活動での時間減衰。`/rating` で表示。
- **おすすめ**：`/recommend <id>` で問題に投票、`/recommendations` で人気順・自分が未ACのものを上位5件。
- **ツイート**：`/tweet` で最新コンテスト結果のツイート文＋投稿リンクを生成（X API 不要）。
- **永続化**：Turso(libSQL) を設定すれば再起動でもデータが消えない（未設定ならローカル SQLite）。

## 技術スタック

| 種別 | 使用技術 |
|---|---|
| 言語 | **Python 3.12**（`libsql-experimental` の native wheel が CPython≤3.12 のみのため固定） |
| Discord | **discord.py 2.x**（app commands / 永続 View ボタン / コンテキストメニュー） |
| PE スクレイピング | **requests** + **beautifulsoup4** + **lxml**（progress ページの解析） |
| 設定 | **python-dotenv**（`.env`） |
| DB | 既定 **SQLite**（標準ライブラリ `sqlite3`） / 永続化 **Turso (libSQL)**（`libsql-experimental`） |
| ホスティング | **Render**（無料・カード不要）＋ **cron-job.org**（keepalive）/ もしくは Oracle Cloud Always Free・自前サーバ(systemd) |
| 常駐補助 | 標準ライブラリ `http.server` によるヘルスエンドポイント（`$PORT`、cron からの ping 先） |

## 仕組み（要点）

- Project Euler は「誰がどの問題を解いたか」の公開 API が無い。bot は **PE の friend の progress
  ページ**（`projecteuler.net/progress=<username>`）を、bot 用アカウントでログインして読み、
  各問題の solved/未solved・難易度%を取得する。これが AC 判定と「全員未AC」抽選の唯一の検証可能な源。
- **friend の solve 状況は `<td>` のクラス `problem_solved` / `problem_unsolved`** に出る
  （`own_problem_*` は閲覧者＝bot 自身の状況なので使わない）。
- **PE 認証**：ログインは CAPTCHA があるので、ブラウザの cookie を種にして運用する
  （本物のセッション cookie は `__Host-PHPSESSID`。`keep_alive` は使い捨てローテーション型で、
  bot は取得した cookie を `pe_cookies.pkl` に永続化して追従する）。
- **friend 追加は自動**：`/register` 実行時、bot が相手の friend key を自分の friends ページへ
  POST 追加する（captcha 無し）。
- **Discord ID は TEXT で保存**：snowflake は 2^53 を超え、libSQL は整数精度を落とすため、
  ID 類は文字列で保持する（メンション破損・channel 取得失敗を防ぐ）。

## コマンド一覧

| コマンド | 用途 |
|---|---|
| `/register <pe_username> <friend_key>` | 参加登録（一度だけ・自動で friend 追加＋progress読取を検証） |
| `/create_contest <start> <contest_type>` | コンテスト作成（誰でも可）。受付ボタン付きで告知 |
| `/submit` | AC した問題を選んで提出（参加者のみ・本人 progress で検証） |
| `/leaderboard` | 順位表（参加者 × 各問題の AC 状況） |
| `/recommend <problem_id>` | 問題を推薦（1人1問1票） |
| `/recommendations` | 人気順のおすすめ問題（自分が未ACのみ・最大5件） |
| `/tweet` | 最新コンテスト結果のツイート文＋投稿リンク |
| `/rating` | コミュニティ・レーティング（AtCoder 風・非活動で減衰） |
| `/introduce` | 自己紹介（10秒で自動削除） |
| `/say <message> <seconds>` | 指定文を喋らせる（1〜3600秒で自動削除） |
| `/service` | コマンド一覧 |
| （bot メッセージを右クリック → アプリ → 「botメッセージを削除」） | bot 投稿の削除（`OWNER` のみ） |

### コンテストの流れ
1. `/create_contest` → **参加受付**告知＋「参加する🙋 / 参加しない🚪」ボタン（この時点では問題未定）。
2. **抽選時刻**に、参加した人の全員未AC問題から自動抽選 → 問題一覧を発表。
   抽選時刻 = `max(now, min(開始-5分, max(開始-1時間, 受付開始+10分)))`。
3. 開始時刻に開始告知 → 制限時間経過で終了 → 順位確定＆レーティング反映。

### 難易度タイプ（`contest.py` の `CONTEST_TYPES` で調整可）
| tier | 難易度% | 問題数 | 制限時間 |
|---|---|---|---|
| `beginner` 初心者 | 1–10% | 4 | 90分 |
| `intermediate` 中級者 | 10–35% | 4 | 120分 |
| `advanced` 上級者 | 30–75% | 3 | 180分 |

開始時刻 `start` は JST・過去不可：`21:00`(今日) / `07-15 21:00`(今年) / `2026-07-15 21:00`。

---

## セットアップ

### 1. Discord bot を作る
1. https://discord.com/developers/applications → **New Application** → 左メニュー **Bot** →
   **Reset Token** で token を取得（`.env` の `DISCORD_TOKEN`）。
2. **OAuth2 → URL Generator** で **`bot` と `applications.commands` の両スコープ**にチェック、
   権限は View Channels / Send Messages / Embed Links / Read Message History / Use Application
   Commands を選び、生成 URL でサーバに招待。
   （`applications.commands` が無いとスラッシュコマンドが登録できず 403 になる）
3. 対象サーバの ID を `.env` の `GUILD_ID` に入れる（開発者モード ON → サーバ右クリック →
   「サーバー ID をコピー」）。`OWNER` に自分の Discord ユーザ名 or ユーザ ID を入れる。

### 2. Project Euler の bot 用アカウント & cookie
1. bot 専用の PE アカウントを作る（無料）。`.env` の `PE_BOT_USERNAME` に設定。
2. ブラウザでその PE アカウントに「Keep me logged in」でログイン。
3. cookie を `.env` に入れる（どちらか）：
   - **推奨**：DevTools → **Network** タブ → ページ再読込 → projecteuler.net のリクエスト →
     **Request Headers** の `Cookie:` の値を**丸ごと** `PE_COOKIE` に貼る
     （`__Host-PHPSESSID=...; keep_alive=...` を含む）。
   - 付属ツール `tools/dump_pe_cookie.py`（`pip install browser_cookie3` 後）でも取得可能。
4. cookie 失効時は `tools/check_pe.py` が `SessionExpired` を報告するので貼り直す。

### 3. （任意）Turso で永続化
- [Turso](https://turso.tech/)（無料・**カード不要**）で DB を作成し、接続 URL と読み書きトークンを取得。
- `.env` の `DB_URL` / `DB_TOKEN_RW` に設定。未設定ならローカル SQLite（Render では再起動で消える）。

### 4. `.env` を用意して実行（ローカル確認）
```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # 編集する
.venv/bin/python tools/check_pe.py   # PE 認証の確認（✅ が出ればOK）
.venv/bin/python bot.py
```

---

## デプロイ

### A. Render + cron-job.org（無料・カード不要・推奨）
Render 無料 Web サービスは 15 分無アクセスでスリープするので、cron-job.org から定期 ping して
起こし続ける。bot は `$PORT` にヘルスサーバを同居させてある（`/` は状態 JSON を返す）。

1. **Render** 登録（カード不要）→ New → **Web Service** → この GitHub リポジトリを接続
   （`render.yaml` があるので Blueprint でも可）。Runtime=Python、Build=`pip install -r requirements.txt`、
   Start=`python bot.py`。Python は `.python-version`（3.12）で固定。
2. ダッシュボードの **Environment** に `.env` の中身を設定（`DISCORD_TOKEN` / `GUILD_ID` / `OWNER` /
   `PE_COOKIE` / `PE_BOT_USERNAME` / `TIMEZONE`、永続化するなら `DB_URL` / `DB_TOKEN_RW`、
   保険で `PYTHON_VERSION=3.12.13`）。
3. デプロイ → 発行 URL（例 `https://<app>.onrender.com`）を控える。`/` を開くと稼働状態 JSON が見える。
4. **cron-job.org** 登録（カード不要）→ その URL を **10 分間隔**で GET するジョブを作る。
5. `/register` などがサーバに出れば完了。

⚠️ Turso 未設定だと Render は揮発ディスクなので、再起動/再デプロイで登録・順位・レーティングが消える。
本番運用では Turso を設定する。

### B. Oracle Cloud Always Free / 自前サーバ（systemd）
Ubuntu 系サーバで `deploy/setup.sh` を実行（git clone / venv / 依存 / systemd unit 設置）：
```bash
curl -fsSL https://raw.githubusercontent.com/TrueRyoB/pe-runner/main/deploy/setup.sh | bash
scp .env <user>@<host>:~/pe-runner/.env         # secrets を転送（コミット不可）
cd ~/pe-runner && .venv/bin/python tools/check_pe.py
sudo systemctl enable --now pe-runner
journalctl -u pe-runner -f
```
永続ディスクなので `pe_runner.db` / `pe_cookies.pkl` はそのまま残る（Turso 任意）。

---

## 運用・トラブルシュート
- **稼働確認**：発行 URL（`/`）が返す JSON に `ready` / `db`(turso|sqlite) / `synced`(コマンド数) /
  `errors` が入る。`tools/check_pe.py` で PE 認証を単体確認できる。
- **コマンドが出ない**：`applications.commands` スコープ付きで再招待し、再デプロイ（`on_ready` で再同期）。
- **PE 認証失敗（`SessionExpired`）**：cookie を取り直して `PE_COOKIE` を更新。
- **状態ファイル**：`pe_runner.db`（SQLite 時）と `pe_cookies.pkl` は gitignore 済み。Turso 使用時は
  データは Turso 側に永続化される。

> 開発時の注意：本番 DB（Turso）に対してテスト目的の破壊的操作（DELETE/DROP 等）を行わないこと。
> DB のテストはローカル SQLite か使い捨ての別 DB で行う。
