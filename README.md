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
1. https://discord.com/developers/applications で「New Application」→ 左メニュー Bot →
   「Reset Token」で token を取得。
2. `applications.commands` と `bot` スコープでサーバに招待。
3. `.env` の `DISCORD_TOKEN` と `GUILD_ID` を設定。

### 3. 実行（ローカル確認）
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 編集する
python bot.py
```

## Oracle Cloud Always Free での常時稼働（PC非依存）

自分のPCに依存せず 24/7 動かすには、Always Free の Ampere A1 (ARM/aarch64) VM 上で
systemd 常駐させる。手順は「① VM作成 → ② setup.sh → ③ secrets転送 → ④ PE認証検証
→ ⑤ 常駐化」の5ステップ。

### ① VM プロビジョニング（Oracle Cloud コンソール）
- Compute → Instances → Create。Shape=**Ampere A1 (VM.Standard.A1.Flex)**、Image=**Ubuntu 22.04+**。
- SSH 公開鍵を登録。**ingress は不要**（Discord/PE への outbound のみ。追加のセキュリティリスト解放は不要）。
- 作成後 `ssh ubuntu@<VM-IP>` で入れることを確認。

### ② サーバ環境構築（VM上で1回）
```bash
curl -fsSL https://raw.githubusercontent.com/TrueRyoB/pe-runner/main/deploy/setup.sh | bash
# git/venv/依存インストール + systemd unit 設置まで自動。再実行で最新コードに更新も可。
```

### ③ secrets（.env）を VM へ転送（自分のPCから）
`.env` は Discord token と PE cookie を含むので **コミットせず scp で運ぶ**：
```bash
scp .env ubuntu@<VM-IP>:~/pe-runner/.env
```

### ④ PE認証をサーバ側で検証（重要）
cookie が **VM の IP からも有効か**を必ず確認する（PEセッションがIP等に紐づく可能性の潰し込み）：
```bash
cd ~/pe-runner && .venv/bin/python tools/check_pe.py     # ✅ 認証OK が出ればOK
```
- ✅ が出れば問題なし。
- ❌（失効）なら、VM側で PE にログインし直した cookie を使うか、cookie を取り直して
  `.env` を更新（このアプリはローテーションを自前で永続化するので初回シードが通ればOK）。

### ⑤ 常駐化 & 疎通確認
```bash
sudo systemctl enable --now pe-runner    # 起動 + 自動起動
sudo systemctl status pe-runner
journalctl -u pe-runner -f               # 「…ログインしたにゃ」を確認
```
Discord サーバに `/register` などが出れば完了。**この時点で自分のPCは落としてよい。**

⚠️ token の二重接続に注意：ローカルでテスト起動している bot は、VMで起動する前に必ず停止する
（同一 token で2プロセスが繋ぐと不安定になる）。

- 依存はすべて aarch64 wheel あり（discord.py / requests / bs4 / lxml）。
- 状態ファイルは repo 直下：SQLite `pe_runner.db` と cookie ジャー `pe_cookies.pkl`。
  バックアップはこの2つをコピーするだけ（どちらも gitignore 済み）。

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
