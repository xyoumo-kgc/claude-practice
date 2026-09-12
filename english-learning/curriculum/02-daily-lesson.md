# 毎日のレッスン形式 + サンプルレッスン

`/english-lesson` はこの形式で毎日のレッスンを生成する。**合計 15〜20 分** で終わる分量にする。

## レッスンの形式（固定）

| パート | 時間 | 内容 |
|-------|------|------|
| 1. 今日の語彙 | 4分 | 新しい単語・表現 **6〜8 個**。意味・発音記号・例文 1 つずつ。すべて音読 |
| 2. 文の形成 | 4分 | 今日の文型 **1 つ**。型 → 例 3 つ → 自分で 3 文作る |
| 3. 発音ガイド | 3分 | 今日の音 **1 つ**。口の形・日本語との違い・ミニマルペア・早口言葉 |
| 4. 実践演習 | 5分 | 穴埋め 5 問 → 並べ替え 3 問 → 日→英 3 問。解答は最後に |
| 5. 記録 | 1分 | 語彙を `progress/vocab-log.md` へ、レッスンを `progress/lesson-log.md` へ |

設計上のポイント:

- 語彙はその日の文型と発音の題材に **再利用** する（同じ語を 3 パートで 3 回触る）
- 演習は「見れば解ける」から「自分で作る」の順に難しくする
- 語彙数・演習数は増やさない。増やすと翌日が続かない

---

## サンプルレッスン: Day 1（フェーズ1・A1）

テーマ: **自己紹介する**

### 1. 今日の語彙（4分）

| # | 英語 | 発音 | 意味 | 例文 |
|---|------|------|------|------|
| 1 | name | /neɪm/ | 名前 | My name is Ken. |
| 2 | from | /frʌm/ ／ 弱く /frəm/ | 〜出身 | I'm from Osaka. |
| 3 | live | /lɪv/ | 住む | I live in Tokyo. |
| 4 | work | /wɜːrk/ | 働く | I work at a bank. |
| 5 | student | /ˈstuːdənt/ | 学生 | I'm a student. |
| 6 | like | /laɪk/ | 好む | I like coffee. |
| 7 | nice | /naɪs/ | すてきな | Nice to meet you. |
| 8 | too | /tuː/ | 〜も | Nice to meet you, too. |

すべての例文を **3 回ずつ音読** する。1 回目はゆっくり、2 回目は普通、3 回目は相手に言うつもりで。

### 2. 文の形成（4分）

**今日の型: I'm + 〜（私は〜です）**

```
I'm  +  名前          I'm Ken.
I'm  +  from + 場所   I'm from Osaka.
I'm  +  a/an + 職業   I'm a student.  /  I'm an engineer.
```

ポイント: 「I am」は会話ではほぼ必ず **I'm** と縮める。職業には **a / an** が付く（日本語にない発想なので最初から型ごと覚える）。

自分の情報で 3 文作る:

1. I'm ________.（名前）
2. I'm from ________.（出身地）
3. I'm a/an ________.（職業・立場）

### 3. 発音ガイド（3分）

**今日の音: /l/（live, like）**

- 舌先を **上の前歯の裏（歯茎）に当てたまま** 声を出す。日本語の「ラ行」は舌が弾くだけで当てっぱなしにしない、ここが違い
- 語頭の /l/ は明るく、語尾の /l/（still, well）はこもった音になるが、まず語頭だけ練習する
- ミニマルペア（/l/ と /r/）: **light / right**, **long / wrong**, **glass / grass**
- 早口言葉（3 回）: *I really like living in a lovely little village.*

### 4. 実践演習（5分）

**A. 穴埋め**（name / from / live / work / like から選ぶ）

1. My ______ is Yuki.
2. I'm ______ Fukuoka.
3. I ______ in Yokohama.
4. I ______ at a hospital.
5. I ______ music.

**B. 並べ替え**

6. [ meet / to / you / nice ] → __________________
7. [ a / I'm / student ] → __________________
8. [ from / I'm / Japan ] → __________________

**C. 日本語 → 英語**

9. 私はエンジニアです。
10. 私は東京に住んでいます。
11. こちらこそ、はじめまして。

<details>
<summary>解答</summary>

1. name 2. from 3. live 4. work 5. like
6. Nice to meet you. 7. I'm a student. 8. I'm from Japan.
9. I'm an engineer. 10. I live in Tokyo. 11. Nice to meet you, too.

よくある間違い: 「I'm engineer」（a/an 抜け）→ 職業には必ず a/an。「I'm live in Tokyo」（be動詞 + 一般動詞の二重）→ I live in Tokyo。
</details>

### 5. 記録（1分）

```bash
python english-learning/scripts/due.py add 語彙 "I'm from ~" "私は〜出身です" "I'm from Osaka." lesson
```

（`/english-lesson` が自動で行う。手動学習のときは上のコマンドで追加する。）

---

## テーマの例（フェーズ別）

| フェーズ | テーマ例 |
|---------|---------|
| 1 | 自己紹介 / 家族 / 数と時間 / 曜日と予定 / 好きなもの / 持ち物 / 場所 / 天気 |
| 2 | カフェで注文 / スーパー / 道をきく / 電話 / 誘う・断る / 週末の話 / 体調 |
| 3 | 昨日の出来事（過去形） / 明日の予定 / 理由を言う（because） / 条件（if） / 比べる |
| 4 | 経験を語る（現在完了） / 助言する（should） / 説明する（関係代名詞） / たられば（仮定法） |
| 5 | 意見と理由 / ニュースの要約 / トラブルを説明 / 交渉 / プレゼンの冒頭 |
