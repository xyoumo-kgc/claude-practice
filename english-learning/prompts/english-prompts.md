# 英語学習プロンプト集（7本）

Claude Code / ChatGPT などに貼り付けて使う、英語学習用の7つのプロンプト。
このリポジトリでは各プロンプトを **Claude Code のスキル**（`/english-…`）として実装しているので、
Claude Code 上では貼り付け不要で `/english-chat` のように呼び出せる。対応表は下記。

| # | 目的 | スキル | 成果物（静的ドキュメント） |
|---|------|--------|------------------------------|
| 1 | 構造化された学習計画 | `/english-plan` | [curriculum/01-learning-plan.md](../curriculum/01-learning-plan.md) |
| 2 | 毎日のレッスン | `/english-lesson` | [curriculum/02-daily-lesson.md](../curriculum/02-daily-lesson.md) |
| 3 | 文法のルールを簡単に | `/english-grammar` | [curriculum/03-grammar-simplified.md](../curriculum/03-grammar-simplified.md) |
| 4 | エラーの修正（添削） | `/english-correct` | ― |
| 5 | レベル別会話練習 | `/english-chat` | ― |
| 6 | 実践的な状況への没入（ロールプレイ） | `/english-roleplay` | ― |
| 7 | 間隔反復レビュー | `/english-review` | [progress/vocab-log.md](../progress/vocab-log.md) |

> 原文の `[言語]` / `[idioma]`（スペイン語で「言語」）は「英語」に置き換えてある。

---

## 1. 構造化された学習計画システム

```text
英語をマスターするための明確で整理された計画を作成してください。

学習を以下のフェーズに分けてください：
- 初心者向けの基礎
- 日常会話スキル
- 文の構築
- 文法の理解
- 実生活での実践的なコミュニケーション
```

```text
Create a clear, well-organized plan for mastering English.

Divide the learning into the following phases:
- Beginner foundations
- Everyday conversation skills
- Sentence construction
- Understanding grammar
- Practical communication in real-life situations
```

## 2. 毎日のレッスンを作成する

```text
英語の毎日のレッスンプランを作成し、以下を含めてください：
- 語彙
- 文の形成
- 発音ガイド
- 短い実践演習

演習が合理的な時間で完了できるようにしてください。
```

```text
Create a daily English lesson plan that includes:
- Vocabulary
- Sentence formation
- A pronunciation guide
- Short practice exercises

Make sure the exercises can be completed in a reasonable amount of time.
```

## 3. 文法のルールを簡略化する

```text
英語の文法をシンプルに説明し、日常会話の例を使ってルールが実際どのように機能するかを示してください。
理論的で抽象的な説明ではなく。
```

```text
Explain English grammar simply, using everyday conversation examples to show how each rule actually works
— not theoretical or abstract explanations.
```

## 4. エラーを修正する

```text
私が提供する英語の書き込みまたは話し言葉の演習を見直し、文法、語彙、文構造のエラーを指摘してください。
修正点を与えて、これらのエラーを避ける方法を説明してください。
```

```text
Review the English writing or speaking exercise I provide and point out errors in grammar, vocabulary,
and sentence structure. Give corrections and explain how to avoid these errors.
```

## 5. レベル別会話練習

```text
英語での会話のパートナーとして振る舞ってください。
とても簡単なフレーズから始め、私が正解するたびに少しずつ難易度を上げてください。
私が詰まったり間違えたりしたら、すぐに助けて正しい形を教えてください。
日常生活の状況（食べ物を注文する、情報を尋ねる、おしゃべりする）について話題を振ってください。
各回答の最後に私の間違いを修正してください。会話の途中で中断しないでください。
```

```text
Act as my English conversation partner. Start with very simple phrases and raise the difficulty a little
each time I answer correctly. If I get stuck or make a mistake, help me right away and show me the correct
form. Bring up everyday situations (ordering food, asking for information, small talk). Correct my mistakes
at the end of each of your replies, without interrupting the conversation.
```

## 6. 実践的な状況への没入

```text
英語でロールプレイのシナリオを作成して、本物の状況を練習させてください：[例：ホテルのチェックイン、就職面接、市場での買い物]。
あなたは相手の役割を演じて、自然な感じで返事してください。
その状況に合った語彙だけを使って、最後に登場した最も役立つ単語と表現のリストを教えてください。
```

```text
Create a role-play scenario in English so I can practice a real situation: [e.g., hotel check-in, a job
interview, shopping at a market]. Play the other person and reply naturally. Use only vocabulary that fits
the situation, and at the end give me a list of the most useful words and expressions that came up.
```

## 7. 学んだことの間隔反復レビュー

```text
英語であなたとすでに勉強した語彙とルールに基づいて、学んだことを定着させるためのクイックレビュー・テストを作成してください。
古い単語と新しい単語を混ぜて、穴埋めフレーズと双方向の翻訳を使用してください。
最後に、私がまだ最も間違えやすい箇所を教えてください。それに集中したいので。
```

```text
Based on the English vocabulary and rules we have already studied together, create a quick review test to
help me retain what I learned. Mix old and new words, and use fill-in-the-blank phrases and translation in
both directions. At the end, tell me which areas I still get wrong most often, so I can focus on them.
```
