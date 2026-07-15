# バーチャルオフィス（Claude エージェント編成）

ピクセルアート調のバーチャルオフィスです。AI社員（Claude Code のエージェント構成）の様子と、
Claude Code の使用量ゲージ（クレジット残の目安）を1画面で見られます。

![構成] office.html（画面）＋ usage.js（データ）＋ update-usage.mjs（データ更新スクリプト）

## すぐ見る

`office.html` をダブルクリックするだけで動きます（サーバー不要）。
初回は usage.js が未更新なので、Claude Code ゲージはサンプル値のままです。

## Claude の使用量を反映させる（Windows）

仕組み: [ccusage](https://github.com/ryoppippi/ccusage)（コミュニティ製）が、ローカルの
Claude Code CLI の会話ログ（`~/.claude/projects/` の JSONL）を集計 → `update-usage.mjs` が
その結果を `usage.js` に書き出し → `office.html` が読み込んで表示します。

> **前提**: Node.js がインストールされていること／ローカルPCで Claude Code CLI を使っていること。
> トークン数ベースの推定なので、公式の `/usage` 表示とは多少ズレます（目安用）。

### 1. 手動で一度動かしてみる

```bat
cd このフォルダ
node update-usage.mjs
```

`usage.js` が書き換わり、`office.html` を開き直すとゲージに反映されます。

### 2. タスクスケジューラで10分おきに自動更新

コマンドプロンプト（管理者不要）で1行:

```bat
schtasks /Create /TN "VirtualOfficeUsage" /TR "\"C:\path\to\virtual-office\update-usage.bat\"" /SC MINUTE /MO 10 /F
```

`C:\path\to\virtual-office` は実際に置いたフォルダに書き換えてください。
GUIでやる場合: タスクスケジューラ → 基本タスクの作成 → トリガー「毎日」＋「繰り返し間隔 10分」→
操作「プログラムの開始」で `update-usage.bat` を指定。

やめたいとき: `schtasks /Delete /TN "VirtualOfficeUsage" /F`

### 3. （おまけ）毎朝7時に会社を開く

```bat
schtasks /Create /TN "OpenVirtualOffice" /TR "cmd /c start \"\" \"C:\path\to\virtual-office\office.html\"" /SC DAILY /ST 07:00 /F
```

## 週ゲージを%表示にする

プランの週上限（トークン数）は公開されていないため、初期状態では週はトークン数表示です。
何週か使って「上限に当たった週の合計トークン数」が分かったら、`update-usage.mjs` の先頭の
`WEEKLY_TOKEN_LIMIT` にその数値を入れると %ゲージになります。

## カスタマイズ

`office.html` 内の配列を書き換えるだけです。

| 変数 | 内容 |
| --- | --- |
| `EMP` | 社員（名前・役割・部屋・状態・いま/完了/つぎ） |
| `ROOMS` | 部屋 |
| `NOTES` | 案件ボードの付箋（`urgent: true` で「急」バッジ） |
| `BOSS_TODO` | 社長のやりたいことリスト |
| `ADVISORS` | 顧問室（スキル一覧） |
| `NEWS` | 下部を流れるニュース |

## 注意

- ccusage はコミュニティ製ツールで、出力形式が変わる可能性があります。取得に失敗すると
  ゲージ下に「取得エラー」と表示されるので、`update-usage.log` を確認してください。
- `usage.js` は使用量の集計値のみで、会話内容は含まれません。
