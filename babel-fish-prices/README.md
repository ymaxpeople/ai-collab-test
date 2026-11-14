# Babel Fish Prices（A3）— Phase 0 スケルトン

InfiniteDriveチェーン（Chain ID 421018）のトークン価格API。
Don't Panic Finance（Uniswap V2フォーク）のプール残高（reserves）から
全トークンのUSD価格を計算して返す、読み取り専用の公開APIの土台です。

- ウォレット・署名・送金は一切なし。オンチェーンへは `eth_call` の読み取りのみ
- 価格は「参考価格」です。流動性が薄いチェーンなので、レンディング等の
  資金判断に使う前提ではありません（仕様 v0.1 の決定事項）

## 仕組み

1. Don't Panic Factory（`0x3157C6AcA800D507af95Ab1466adBA3A6F11eE1a`）の
   `getPair` でペアを解決する（ペアアドレスはハードコードしない）
2. 各ペアの `token0/token1/getReserves` を読み、decimals補正してスポット価格を出す
3. USD価格へのルート優先順位: USDT直結 → 42経由 → FISH経由 → なければ `price: null`
   （0は絶対に返さない）
4. 価格には流動性USD・信頼度ラベル（A/B/C/unpriced）をセットで返す。
   信頼度は設計ドラフトのしきい値（プール $40K/$15K/$3K、ホップ数、3ホップで1段下げ）
   を適用し、最後に「アンカー（42-USDT）の信頼度を超えない」上限ルールをかける
5. スポット価格はSQLiteにスナップショットとして貯め、TWAPはその平均で返す
   （履歴が足りない間は `twap: null` + 理由を返す。スポットとTWAPの乖離が
   20%を超えると `divergence_warning: true`）
6. RPCは複数エンドポイントのフェイルオーバー。ネイティブ通貨42は
   センチネルアドレス（`0xEeee...EEeE`、`symbol()` は "42"、decimals 18）
   としてペア解決する。トークンの decimals は原則オンチェーンで読む
   （ブリッジUSDTは18桁。6桁と決め打ちすると価格が10^12倍ずれる）

## 動かし方

依存は Python 3 と `requests` のみ（HTTP層は標準ライブラリ）。

```bash
# 通常モード（RPCへ読み取り接続する）
python3 main.py --port 8080

# フィクスチャモード（オフライン。検証済み実データの固定値で動く）
BABELFISH_FIXTURE=1 python3 main.py --port 8080

# テスト（オフライン、pytest不要）
python3 run_tests.py
```

環境変数: `BABELFISH_REFRESH_SECONDS`（再取得間隔、既定60秒）、
`BABELFISH_DB`（SQLiteの場所）、`BABELFISH_RPC_SLEEP`（eth_call間の待機秒、既定1.0）

## エンドポイント

| パス | 内容 |
|---|---|
| `GET /health` | 状態、モード、最終リフレッシュ時刻 |
| `GET /v1/prices` | 全トークンの価格一覧（unpriced は `price: null` で含む） |
| `GET /v1/price/{tokenAddress}` | 1トークンの価格 |
| `GET /v1/twap/{tokenAddress}?window=1h\|24h` | TWAP（履歴不足なら null + note） |
| `GET /v1/pairs` | Phase 0 ペアの残高一覧 |

価格オブジェクトの主なフィールド: `price`, `liquidity_usd`,
`staleness_seconds`（不明なら null）, `confidence`, `route`（例 `["FISH","42","USDT"]`）,
`divergence_warning`

## フィクスチャモードについて

`BABELFISH_FIXTURE=1` ではRPCに一切つながず、検証済みの実データ2ペア
（42/DONT の 2026-11-12 実測reserves、FISH-42 の 2026-11-13 残高）と
アンカー価格 42 = $0.6345（2026-11-12時点の参考値）だけで計算します。
フィクスチャに無いトークンは `price: null` になります。デモと回帰テスト用です。

## 現在の状態・限界（Phase 0 スケルトン）

- **ライブ検証は grokbot の環境で実施済み（2026-11-14）**：8ペア全部の
  reserves を実測し（ブロック4415839〜4415842）、decimals修正後の再計算で
  42 $0.65663 / FISH $1.28615 / PANIC $0.00038900 などを取得。
  その際のレビューで見つかった必須修正6件（USDT decimals、3ホップの
  二重格下げ、unpriced時の価格返却、ゼロ残高プール、TWAPの大文字小文字、
  DBのモード混在）は反映済み。Don't Panic の画面表示との照合は未実施。
  Muse の実行環境からは出口プロキシの都合でRPCに届かないため、
  ライブ実行の再確認はRPCに届く環境で行うこと
- TWAPはスナップショット平均方式の足場。設計ドラフト本来の
  V2累積価格（priceCumulativeLast）方式は後続フェーズ
- 信頼度しきい値のうち 24h出来高と最終取引時刻は、データが取れている
  ときだけ効く（Phase 0 では多くが未取得のため流動性＋ホップ数が主軸）
- 流動性USDは「そのトークンの最初のホップのプールの両側合計」で、
  信頼度判定もそのプールに対して行う
- KETはルート判明済み（KET→FISH→42→USDT の3ホップ）だが分類は実測待ち
- GUIDE / SOV / VIC / BFOXX はアドレス未確認のためシンボルのみで
  unpriced として載せている（TOWELはDEX掲載アドレスを確認済み）

## 構成

```
main.py                  起動エントリ
run_tests.py             オフラインのテストランナー
babelfish/
  config.py              アドレス・ペア・しきい値などの定数
  rpc.py                 読み取り専用RPCクライアント（フェイルオーバー）
  datasource.py          ライブ／フィクスチャのデータ源
  fixtures.py            フィクスチャ実データ（出典つき）
  engine.py              価格計算・ルート・信頼度
  store.py               SQLiteスナップショットとTWAP
  service.py             リフレッシュとレスポンス組み立て
  server.py              標準ライブラリのHTTPサーバー
tests/test_engine.py     テスト本体
```
