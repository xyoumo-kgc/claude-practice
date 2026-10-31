# claude-practice

Claude Codeの練習用リポジトリです。

## 目的

- Claude Codeの使い方を学ぶ
- GitとGitHubの基本的なワークフローを練習する
- PRの作成・レビューを体験する

## 使い方

このリポジトリはClaude Codeと一緒に学習するための練習場所です。

## FX ツール（このリポジトリで作ったもの）

| ツール | 中身 | 入口 |
|---|---|---|
| **FUSION-CORE** | 賢人のデイトレード × 100億円トレーダーの共通点を機械化した融合システム。仕様・Python 参照実装・事前登録した実データ検証（**最終検証は不合格**：優位性を確認できず、裁量の補助ツールとして提供） | [fusion/README.md](fusion/README.md)、[結果](fusion/RESULTS.md) |
| FUSION-CORE の MT5 EA | シグナル通知・パネル・任意の自動売買 | [mt5/README_FUSION.md](mt5/README_FUSION.md) |
| FUSION-CORE ダッシュボード | MT5 の H1 足 CSV を読み込み、いまの判定・チャート・過去の成績を表示 | `streamlit run dashboard/fusion_app.py` |
| チャート分析スキル | `/fx-fusion`（融合システム）、`/fx-analyze`（100億円トレーダーの4パターン） | [.claude/commands/](.claude/commands/) |
| 2人の考え方の比較 | 反証検証を経た共通点・相違点・系譜 | [fusion/THEORY.md](fusion/THEORY.md) |
| 旧システム | 従来版EA・4P-Score（実データでは優位性を確認できなかった） | [mt5/README_SIGNAL.md](mt5/README_SIGNAL.md) |

投資助言ではありません。成績の検証方法と結果は [fusion/RESULTS.md](fusion/RESULTS.md) にあります。
