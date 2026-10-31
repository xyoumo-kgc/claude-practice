# fusion/ — 賢人のデイトレード × 100億円トレーダー 融合システム FUSION-CORE（Python参照実装・検証基盤）

**FUSION-CORE** は、2人の手法のうち反証検証を経ても残った中核セットアップを、機械的なルールにしたものです
（どこが共通でどこが違うかは [THEORY.md](THEORY.md)）。

> 4時間足レベルの上昇（下降）構造の中で、押し（戻り）が 4H MA（1時間足の SMA80）に届き、4H MA が逆向きでないときに、
> 1時間足で「安値切上げを保ったまま戻り高値を上抜ける」瞬間を逆指値で取る。損切りは切上げ安値の外。
> 出口は「4Hレベルの新しい押し安値ができるたびに損切りを引き上げる」と「週末・休場前の全決済」だけ。

| 用途 | ファイル |
|---|---|
| 仕様（凍結） | [SPEC.md](SPEC.md) |
| 2人の考え方の比較と反証検証 | [THEORY.md](THEORY.md) |
| 最終検証の事前登録 | [PREREGISTRATION.md](PREREGISTRATION.md) |
| 最終検証の結果 | [RESULTS.md](RESULTS.md) |
| Python 参照実装 | `strategy.py` |
| MT5 EA（通知・パネル・任意の自動売買） | `../mt5/FX_Fusion_EA.mq5`、[../mt5/README_FUSION.md](../mt5/README_FUSION.md) |
| ダッシュボード | `../dashboard/fusion_app.py`（`streamlit run dashboard/fusion_app.py`） |
| チャート分析スキル | `/fx-fusion`（[`.claude/skills/fx-fusion/SKILL.md`](../.claude/skills/fx-fusion/SKILL.md)） |

```
fusion/
├── data.py        # データ読み込み（backtesting.py同梱EURUSD / OANDA 1分足 / MT5書き出しCSV）→ MT5風サーバー時間
├── indicators.py  # SMA・ATR（MT5と同じ定義）、スイング検出、確定済み上位足の対応づけ
├── features.py    # 節目（水平線）の抽出、MA収束→拡散、リスクリワード（初期の部品）
├── broker.py      # 約定シミュレーター（スプレッド・窓開け・損切り優先・部分利確・建値移動）
├── engine.py      # 汎用のバー駆動エンジン（初期の部品。FUSION-CORE は strategy.py の専用ループを使う）
├── stats.py       # R単位の成績集計
├── baselines.py   # 比較用: 従来版EA（MAスロープ）・4P-Score を先読みなしで再実装
├── strategy.py    # ★FUSION-CORE v1.0 の参照実装（全変種・感度・素朴ベースライン・snapshot）
├── evaluate.py    # 開発期間(IS)/検証期間(OOS)に分けた実データ検証
├── final_eval.py  # 事前登録どおりの最終検証（未接触データで1回だけ実行）
├── mt5_parity.py  # MT5 EA のログと Python の判定の照合
└── tests/         # python -m unittest discover -s fusion/tests -t .（golden/ に照合用の取引一覧）
```

## すぐ試す

```python
from fusion import data as fd, strategy as fs
h1 = fd.load_mt5_csv('EURUSD_H1.csv')                  # MT5 で書き出した H1 足（または fd.load_backtesting_eurusd()）
trades, funnel = fs.run_h1(h1, 'EURUSD')                 # 既定構成（fusion）の取引一覧と、理由コード別の件数
snap = fs.snapshot(h1, 'EURUSD')                         # 最後の確定足での状態（待機注文・建玉・方向ごとの判定）
```

## 先読み（ルックアヘッド）を防ぐ約束

| 対象 | ルール |
|------|--------|
| 判定 | 確定した足の終値で行い、エントリーは**次の足の始値**（成行） |
| スイング | 左右 `depth` 本が確定して初めて認識（MQL5 の `FindSwingHighs/Lows` と同じ不等号・同じ探索範囲） |
| 上位足 | 実行足の確定時刻までに**確定した**4時間足・日足だけを参照（`closed_index_map`） |
| 約定 | 同じ足で損切りと利確の両方に届いたら損切りを優先。寄り付きが損切りを越えたら寄り付きで約定 |

`tests/test_infra.py` の `test_no_lookahead_on_truncation` は、データを途中で切っても過去の計算結果が
変わらないことを確かめています。

## データの準備

### A. すぐ使えるデータ（インストール済みなら）
`pip install backtesting` に同梱の EURUSD 1時間足（2017-04〜2018-02、5,000本）。`data.load_backtesting_eurusd()` で読めます。

### B. 複数年・複数銘柄（推奨）
OANDA の1分足（2005〜2020、UTC）を公開しているリポジトリから、必要な年だけ取り出します。

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/FutureSharks/financial-data
cd financial-data
git sparse-checkout set pyfinancialdata/data/currencies/oanda/EUR_USD/2013 ...（必要な銘柄/年）
python -c "from fusion.data import prepare_oanda; prepare_oanda('EUR_USD', '<...>/pyfinancialdata/data/currencies/oanda', 'data')"
```
→ `data/EURUSD_M15.csv / _H1.csv / _H4.csv / _D1.csv` ができます（サーバー時間 = NY時間+7時間）。

### C. 自分のMT5のデータ（ドル円・GOLDなど）
MT5 の「表示 → 銘柄 → チャートバー」で H1（あれば M15 も）を書き出し、

```bash
python -m fusion.evaluate --data-dir data --symbols USDJPY --mt5 USDJPY_H1.csv USDJPY_M15.csv
```

## 検証の実行

```bash
python -m fusion.evaluate --data-dir data --periods IS        # 開発中は開発期間だけを見る
python -m fusion.final_eval --data-dir <H1/M15 のフォルダ> --out <出力フォルダ>   # 事前登録どおりの最終検証（1回だけ）
```

## 最終検証の結果（2026-10-31、未接触データで1回だけ）

**FUSION-CORE v1.0 は不合格でした**（合格基準 P1〜P6 をすべて満たさず。詳細は [RESULTS.md](RESULTS.md)）。

| システム | 未接触データ 合算（7銘柄・約15年） | 当初の検証期間（4銘柄 2018-01〜2020-05） |
|---|---|---|
| **FUSION-CORE（fusion）** | 1,609回 / 平均 +0.055R / PF1.08（t=1.07） | 276回 / +11.1R / PF1.06 |
| 100億の要素だけ（oku_only） | 222回 / −0.022R / PF0.96 | 36回 / −2.9R / PF0.82 |
| 賢人の要素だけ（kenjin_only） | 347回 / −0.166R / PF0.78 | 61回 / −10.5R / PF0.78 |
| 従来版EA（MAスロープ） | 4,420回 / −0.007R / PF0.99 | 870回 / −66.9R / PF0.89 |
| 4P-Score（パターン①, A以上） | 539回 / −0.027R / PF0.96 | 99回 / −16.8R / PF0.76 |
| 素朴ベースライン（トレンド方向にでたらめに入る・同じ出口、20シード平均） | 約1,850回 / +0.019R | — |

- 点推定では fusion がいちばん良いものの、ゼロとも素朴ベースラインとも区別できません。
- 利益は週末まで持った少数の取引に頼っています（上位1%を除くと −0.058R）。
- 従来版EA と 4P-Score は、合成データでは好成績でした。これは生成器にトレンドの持続性を組み込んでいたためで、実データではどちらも優位性がありませんでした。

## 検証プロトコル（結果を見る前に決めたルール）

過剰最適化（過去データへの当てはめすぎ）を避けるため、次の手順を**融合システムの結果を見る前に**固定しました。

1. 開発は**開発期間（2013-01〜2017-12）だけ**で行う。検証期間（2018-01〜2020-05）は仕様を固定するまで見ない。
2. パラメータは仕様書の既定値（理論から決めた値）のまま。開発期間の結果に合わせた数値調整はしない
   （明らかな実装バグの修正は除く）。
3. 構成要素の取捨は、アブレーション（1要素ずつ外した版）の比較だけで決める。ある要素を外した版が
   「4銘柄合算の平均Rで標準誤差以上に良く、かつ4銘柄中3銘柄以上で良い」ときに限り、その要素を外す。
4. 固定した構成で検証期間を**1回だけ**評価し、良くても悪くもそのまま報告する。
   比較対象（従来版EA・4P-Score・100億のみ・賢人のみ）の検証期間の成績も併記する。
