# バーチャルオフィス（Claude エージェント編成）

ピクセルアート調のバーチャルオフィスです。AI社員（Claude Code のエージェント構成）の様子と、
Claude Code の使用量ゲージ（クレジット残の目安）を1画面で見られます。

![構成] office.html（画面）＋ usage.js（データ）＋ update-usage.mjs（データ更新スクリプト）

## すぐ見る

`office.html` をダブルクリックするだけで動きます（サーバー不要）。
初回は usage.js が未更新なので、Claude Code ゲージはサンプル値のままです。

## Claude の使用量を反映させる（Windows・ワンクリック）

仕組み: [ccusage](https://github.com/ryoppippi/ccusage)（コミュニティ製）が、ローカルの
Claude Code CLI の会話ログ（`~/.claude/projects/` の JSONL）を集計 → `update-usage.mjs` が
その結果を `usage.js` に書き出し → `office.html` が読み込んで表示します。

> **前提**: Node.js がインストールされていること／ローカルPCで Claude Code CLI を使っていること。
> トークン数ベースの推定なので、公式の `/usage` 表示とは多少ズレます（目安用）。

### セットアップ: `setup.bat` をダブルクリックするだけ

以下を全部自動でやります:

1. Node.js の確認
2. 使用量の初回取得（`usage.js` 生成）
3. タスクスケジューラに「10分おきの自動更新」を登録
4. （聞かれて y と答えたら）「毎朝7時にオフィスを開く」も登録
5. オフィスを開く

やめたいとき: `uninstall.bat` をダブルクリック（登録したタスクを削除します）。

<details>
<summary>手動でやる場合のコマンド</summary>

```bat
node update-usage.mjs
schtasks /Create /TN "VirtualOfficeUsage" /TR "\"C:\path\to\virtual-office\update-usage.bat\"" /SC MINUTE /MO 10 /F
schtasks /Create /TN "OpenVirtualOffice" /TR "cmd /c start \"\" \"C:\path\to\virtual-office\office.html\"" /SC DAILY /ST 07:00 /F
```
</details>

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
