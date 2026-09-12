# 英語学習システム

Claude Code を「英語の家庭教師」にするための一式。7 つの学習プロンプトを **スキル**（`/english-…`）として実装し、
学習計画・レッスン形式・文法ガイドの静的ドキュメントと、**間隔反復用の進捗ログ** を組み合わせている。

```
english-learning/
├── README.md                       # このファイル
├── curriculum/
│   ├── 01-learning-plan.md         # 5フェーズの学習計画（基礎 → 日常会話 → 文の構築 → 文法 → 実践）
│   ├── 02-daily-lesson.md          # 毎日のレッスン形式（15〜20分）+ サンプル Day 1
│   └── 03-grammar-simplified.md    # 文法を会話例でつかむ（16項目）
├── prompts/
│   └── english-prompts.md          # 元になった7つのプロンプト（日本語・英語）
├── progress/                       # 学習ログ（スキルが自動で追記。git で履歴が残る）
│   ├── status.md                   # 現在のフェーズ・週の予定
│   ├── vocab-log.md                # 語彙・表現・文法（Box と次回復習日つき）
│   ├── mistakes-log.md             # 間違い（分類つき）
│   └── lesson-log.md               # 実施記録
└── scripts/
    └── due.py                      # 間隔反復の期日計算・採点反映（標準ライブラリのみ）

.claude/skills/
├── english-plan/      # 1. 学習計画 + レベル診断
├── english-lesson/    # 2. 毎日のレッスン
├── english-grammar/   # 3. 文法を簡単に
├── english-correct/   # 4. 添削
├── english-chat/      # 5. レベル別会話練習
├── english-roleplay/  # 6. ロールプレイ
└── english-review/    # 7. 間隔反復レビュー
```

## 使い方

リポジトリのルートで Claude Code を起動し、スキルを呼ぶ。

| やりたいこと | コマンド | 目安時間 |
|-------------|---------|---------|
| 初回セットアップ・レベル診断 | `/english-plan` | 10分 |
| 今日のレッスン | `/english-lesson`（テーマ指定可: `/english-lesson カフェで注文`） | 15〜20分 |
| 文法を会話例で理解する | `/english-grammar 現在完了` | 5〜10分 |
| 書いた英文を添削してもらう | `/english-correct` のあとに英文を貼る | 5〜10分 |
| 会話練習（正解するほど難しくなる） | `/english-chat` | 10〜15分 |
| 場面別ロールプレイ | `/english-roleplay ホテルのチェックイン` | 15〜20分 |
| 復習テスト（毎日の最初に） | `/english-review` | 5〜10分 |

### 1週間の流れ（例）

```
月水金: /english-review → /english-lesson
火木  : /english-review → /english-chat
土    : /english-roleplay
日    : /english-review（まとめ）→ status.md を見直す
```

詳しくは [curriculum/01-learning-plan.md](curriculum/01-learning-plan.md)。

## 間隔反復のしくみ

学んだ語彙・表現・文法は `progress/vocab-log.md` に **Box（1〜5）** と **次回復習日** つきで記録される（ライトナー方式）。

| Box | 次回復習までの日数 |
|-----|------------------|
| 1 | 1日 |
| 2 | 3日 |
| 3 | 7日 |
| 4 | 14日 |
| 5 | 30日 |

`/english-review` は期限の来た項目（古いもの）と最近学んだ項目（新しいもの）を混ぜて出題し、
正解なら Box を 1 つ上げ、不正解なら Box 1 に戻す。間違いは `mistakes-log.md` に分類つきで溜まり、
「最も間違えやすい箇所」の報告に使われる。

スクリプトは手動でも使える:

```bash
python english-learning/scripts/due.py list            # 今日の復習対象
python english-learning/scripts/due.py add 語彙 "grab a bite" "軽く食べる" "Let's grab a bite." lesson
python english-learning/scripts/due.py grade 3 ok 4 ng  # 採点を反映
python english-learning/scripts/due.py stats           # Box 別件数と間違いの分類集計
```

## 設計方針

- **毎日 15〜25 分** で回る分量に固定する。増やさない
- **会話例から文法へ**。抽象的な説明はしない（`03-grammar-simplified.md`）
- **会話中は中断しない**。訂正は返答の末尾か、ロールプレイの終了後にまとめる
- **間違いは資産**。すべてログに残し、復習と弱点報告に使う
- ログは Markdown なので、git の履歴がそのまま学習記録になる

## 前提・注意

- 学習者は日本語話者の大人を想定している。説明は日本語、英語素材は英語
- 計画の「目安期間」は推測であり、進級は各フェーズの卒業チェックで判断する
- 発音はテキストでの指導になる。音声で確認したい場合は、リポジトリの `narration` スキルや音声合成を併用する
