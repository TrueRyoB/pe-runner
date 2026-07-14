# pe-runner

不特定多数の参加者と Project Euler をコンテスト形式で解く Discord bot。

## 仕組み（要点）

- 参加者は一度 `/register <PEユーザ名> <friend key>` するだけ。以降は毎回の自己申告不要。
- bot は PE の **friend の progress ページ**（`projecteuler.net/progress=<username>`）を読み、
  各問題の solved/未solved・難易度%・solve時刻を取得する。これが AC 判定と「全員未AC」選抜の
  唯一かつ検証可能なデータ源。
- AC 判定は信頼ベースではなく **実検証**（提出時に本人 progress を再取得して確認）。
- スコアは **難易度%＝得点**、同点は最終AC時刻で tiebreak。

## セットアップ

### 1. Project Euler 側
1. bot 専用の PE アカウントを1つ作る（無料）。
2. ブラウザで「Keep me logged in」で projecteuler.net にログインする。
   その後、cookie を `.env` の `PE_SESSION_COOKIE` に入れる。取得方法は2通り:

   **方法A（おすすめ・コマンド一発）**: 付属ツールがローカルブラウザから読み出して
   `.env` に貼れる形で出力する。`PHPSESSID` は HttpOnly なので console の
   `document.cookie` では読めない → このツールを使う。
   ```bash
   # browser_cookie3 はセットアップ時の .venv に入れておく
   #（未導入なら: python3 -m pip install browser_cookie3  ※ pip 単体は使えないことが多い）
   .venv/bin/python tools/dump_pe_cookie.py            # 全ブラウザを試す
   .venv/bin/python tools/dump_pe_cookie.py chrome     # ブラウザ指定
   ```
   出力の `PE_SESSION_COOKIE=PHPSESSID=...` 行をそのまま `.env` に貼る。
   （macOSでChrome系は Keychain の確認が出ることがあるが正常）

   **方法B（インストール不要）**: DevTools → **Network** タブでページを再読込 →
   projecteuler.net へのリクエストを選択 → **Request Headers** の `Cookie:` に
   `PHPSESSID=...` が入っている。それをコピー。
   （Application → Cookies → projecteuler.net からも見える）

   - ※ PE ログインは CAPTCHA があるため自動ログインはしない。cookie 方式で運用する。
   - ※ cookie 失効時は bot が `SessionExpired` を通知するので、都度貼り直す
     （方法Aを再実行するのが速い）。
3. **friend 登録**: 参加者の friend key を bot アカウントの friends ページに追加する
   （運営が手動追加。これで bot がその人の progress を読めるようになる）。

### 2. Discord 側
1. https://discord.com/developers で Application → Bot を作成し、token を取得。
2. `applications.commands` と `bot` スコープでサーバに招待。
3. `.env` の `DISCORD_TOKEN` と `GUILD_ID` を設定。

### 3. 実行（ローカル確認）
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 編集する
python bot.py
```

## Oracle Cloud Always Free での常時稼働

Ampere A1 (ARM/aarch64) の Always Free VM 上で systemd 常駐させる。

```bash
# VM 上（Ubuntu想定）
sudo apt update && sudo apt install -y python3-venv git
git clone <your-repo> pe-runner && cd pe-runner
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env        # token / cookie を設定

sudo cp deploy/pe-runner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pe-runner
sudo systemctl status pe-runner
journalctl -u pe-runner -f               # ログ
```

- 依存はすべて aarch64 wheel あり（discord.py / requests / bs4 / lxml）。
- SQLite はファイル 1 つ（`pe_runner.db`）。バックアップはこのファイルをコピーするだけ。

## コマンド

| コマンド | 用途 |
|---|---|
| `/register <pe_username> <friend_key>` | 参加登録（一度だけ） |
| `/create_contest <name> <start> <duration_minutes> <contest_type> <num_problems>` | コンテスト作成（運営のみ）。`start` は `YYYY-MM-DD HH:MM` |
| `/submit` | ACした問題を選んで提出（本人 progress を再取得して検証） |
| `/leaderboard` | 現在の順位表 |

### contest_type（難易度分布プリセット）
- `sprint` — easy寄り（易しめ短時間向け）
- `balanced` — easy/medium/hard を均等寄り
- `marathon` — hard寄り（難問中心）

`contest.py` の `CONTEST_TYPES` / `BUCKETS` を編集すれば分布は自由に調整可能。

## 既知の詰め（実装後に確認したい点）
- **friend ページの HTML クラス名**: 手元サンプルは自分のページ（`own_problem_solved`）。
  friend 閲覧時にクラス名が同一か、実物 1 件で確認（パーサは "unsolved" 部分文字列で判定する
  ので多少の差異は吸収するが、要確認）。
- **セッション失効**: 長期運用では cookie 貼り直しが要る。永続 cookie を入れると頻度が下がる。
- **friend 自動追加**: 現状は運営が手動追加。将来 friends ページへの POST 自動化も可能（未検証）。
- **認証スクレイプ**: 私的・小規模用途なので過剰 poll はせず `/submit` 起点で取得している。
