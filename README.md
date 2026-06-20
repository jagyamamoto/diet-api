# namecard-api

名刺を iPhone で撮影し、連絡先（電話帳）に自動登録するための無料バックエンド。
Eight のような名刺管理を、iOS標準のショートカット＋自前APIで実現します。

## 仕組み

```
[iPhone]                                [このAPI]
名刺を撮影
  ↓
画像からテキストを抽出（iOS標準OCR・無料）
  ↓ text を送信 ──────────────────────→  POST /parse_card で解析
連絡先に登録  ←── vCard / JSON を受信 ────  vCard / JSON を返す
```

撮影とOCRは iPhone 側（無料・オフライン）で行い、文字列の解析（氏名・会社・
役職・電話番号などへの振り分け）だけをこのAPIが担当します。

## エンドポイント

### `GET /`
ヘルスチェック。`{"status": "ok"}` を返します。

### `POST /parse_card`
名刺のOCRテキストを構造化します。

| フィールド | 必須 | 説明 |
|---|---|---|
| `text` | ✓ | OCRで抽出した名刺の生テキスト |
| `format` | | `json`（既定） / `vcard` / `both` |

抽出項目: 氏名 / 会社名 / 役職 / 電話 / 携帯 / FAX / メール / URL / 郵便番号 / 住所

レスポンス例（`format=json`）:

```json
{
  "data": {
    "name": "山田 太郎",
    "company": "株式会社サンプル商事",
    "title": "営業部 部長",
    "tel": "03-1234-5678",
    "mobile": "090-1234-5678",
    "fax": "03-1234-5679",
    "email": "taro.yamada@example.co.jp",
    "url": "https://www.example.co.jp",
    "postal": "100-0001",
    "address": "東京都千代田区千代田1-1-1"
  }
}
```

`format=vcard` の場合は `text/vcard` 形式で vCard 3.0 を返すので、
ショートカットでファイルに保存して開くだけで連絡先登録ダイアログが出ます。

## iPhone ショートカットの組み立て

1. **写真を撮る**（カメラ）
2. **画像からテキストを抽出**
3. **URLの内容を取得**（POST, `<このAPIのURL>/parse_card`、本文＝フォーム、`text`＝手順2、`format`＝`vcard`）
4. 返ってきた vCard を **ファイルに保存 → 開く**（または「連絡先を追加」）

## ローカル実行

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# http://127.0.0.1:8000/docs で動作確認
```

## 解析エンジン（ルール / AI）

`POST /parse_card` は2通りの解析方式を持ち、レスポンスの `engine` で判別できます。

| engine | 条件 | 特徴 |
|---|---|---|
| `gemini` | 環境変数 `GEMINI_API_KEY` が設定済み | Google Gemini（無料枠）で解析。氏名（漢字/カタカナ/英語）や向きの乱れに強い |
| `rules`  | キー未設定 or API失敗時に自動フォールバック | 正規表現ベース。APIキー不要で常に動く |

### Gemini を使う（推奨・無料枠）

1. [Google AI Studio](https://aistudio.google.com/apikey) で API キーを無料発行
2. 環境変数を設定：
   - `GEMINI_API_KEY` … 発行したキー（必須）
   - `GEMINI_MODEL` … 任意。既定は `gemini-2.0-flash`

キーは無料枠で運用でき、依存パッケージの追加も不要（標準ライブラリで呼び出し）。

## デプロイ（Render 無料枠）

`render.yaml` を含むこのリポジトリを Render の Blueprint として接続すると、
`namecard-api` という Web サービスとして公開されます。
AI解析を使う場合は、Render のサービス設定で環境変数 `GEMINI_API_KEY` を追加してください
（未設定でもルール解析で動作します）。
無料枠はアイドル時にスリープするため、初回アクセスは数十秒かかることがあります。
