# fusion/ — 100億円トレーダー × 賢人のデイトレード 融合システム（Python参照実装・検証基盤）

MT5用EA（`mt5/FX_Fusion_EA.mq5`）と同じ判定をPythonで再現し、**実データで先読みなしに検証する**ための
パッケージです。

```
fusion/
├── data.py        # データ読み込み（backtesting.py同梱EURUSD / OANDA 1分足 / MT5書き出しCSV）→ MT5風サーバー時間
├── indicators.py  # SMA・ATR（MT5と同じ定義）、スイング検出、確定済み上位足の対応づけ
├── features.py    # 節目（水平線）の抽出、MA収束→拡散、リスクリワード
├── broker.py      # 約定シミュレーター（スプレッド・窓開け・損切り優先・部分利確・建値移動）
├── stats.py       # R単位の成績集計
├── baselines.py   # 比較用: 従来版EA（MAスロープ）・4P-Score を先読みなしで再実装
├── evaluate.py    # 開発期間(IS)/検証期間(OOS)に分けた実データ検証
└── tests/         # python -m unittest discover -s fusion/tests -t .
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
python -m fusion.evaluate --data-dir data --periods IS,OOS    # 仕様を固定した後に1回だけ検証期間を見る
```

## 既存システムの実データ成績（先読みなし・スプレッド込み）

OANDA 2013-01〜2020-05、EURUSD・GBPUSD・EURJPY・XAUUSD（GOLD）の4銘柄合算:

| システム | 開発期間 2013-2017 | 検証期間 2018-2020 |
|---|---|---|
| 従来版EA（MAスロープ） | 1,791回 / +58.6R / PF1.05 | 870回 / **−66.9R** / PF0.89 |
| 4P-Score（パターン①, A以上） | 170回 / −4.2R / PF0.96 | 99回 / **−16.8R** / PF0.76 |

どちらも実データでは優位性が確認できませんでした（合成データでの好成績は、生成器にトレンドの持続性を
組み込んでいたことによるものでした）。融合システムはこの2つを比較対象にしています。
