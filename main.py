"""Namecard API

iPhoneのショートカット「画像からテキストを抽出」で得た名刺のOCRテキストを
受け取り、氏名・会社・役職・連絡先などに振り分けて、構造化データ／vCard を返す。

撮影とOCRはiOS側（無料・オンデバイス）で行い、解析だけをこのAPIが担当する。
Eight のような名刺管理を、無料・自前運用で実現するためのバックエンド。
"""

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import PlainTextResponse
import re, os, json, urllib.request

app = FastAPI(title="Namecard API", version="1.0.0")

# 抽出する項目（ルール解析・AI解析で共通のキー）
# name_alt: 名刺に氏名が2言語で併記されている場合の、もう一方の表記
CARD_FIELDS = [
    "name", "name_alt", "company", "title",
    "tel", "mobile", "fax",
    "email", "url", "postal", "address",
]


@app.get("/")
def health():
    """疎通確認用のヘルスチェック"""
    return {"status": "ok", "service": "namecard-api"}


# =========================================================
# 名刺OCR解析
# =========================================================

# 会社名・組織を示すキーワード
ORG_KEYWORDS = [
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
    "一般社団法人", "公益社団法人", "一般財団法人", "公益財団法人",
    "特定非営利活動法人", "医療法人", "学校法人",
    "Inc", "Corp", "Corporation", "Co.,", "Co.,Ltd", "Ltd", "LLC", "K.K", "Company",
]

# 役職を示すキーワード
TITLE_KEYWORDS = [
    "代表取締役", "取締役", "代表", "会長", "社長", "副社長", "専務", "常務",
    "本部長", "部長", "次長", "課長", "係長", "主任", "主査", "室長", "支店長",
    "店長", "工場長", "所長", "局長", "顧問", "理事", "監事", "執行役員", "役員",
    "マネージャー", "マネジャー", "リーダー", "ディレクター", "プロデューサー",
    "エンジニア", "デザイナー", "コンサルタント", "プランナー", "スタッフ",
    "CEO", "COO", "CFO", "CTO", "CISO", "President", "Director", "Manager",
    "Officer", "Engineer", "Designer", "Consultant", "Producer", "Founder",
]

# 各種抽出用の正規表現
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
RE_URL = re.compile(r"(?:https?://|www\.)[A-Za-z0-9./?=&%_\-#~]+", re.IGNORECASE)
# 郵便番号（前後が数字/ハイフンでない＝電話番号の一部を誤検出しない）
RE_POSTAL = re.compile(r"〒?\s*(?<![\d-])(\d{3}[-－]\d{4})(?![\d-])")
# 電話番号（市外局番0始まり/携帯/国際表記+81 に対応、前後の数字境界を厳格化）
RE_PHONE = re.compile(
    r"(?<![\d+])((?:\+?81[-\s.]?|0)\d{1,4}[-\s.（(]?\d{1,4}[-\s.）)]?\d{3,4})(?!\d)"
)
# 名前らしい行（漢字/かな主体で空白区切りの2語：例「西 宏司」）
RE_JP_NAME = re.compile(r"^[一-鿿぀-ヿ々ヶ]{1,5}[\s　]+[一-鿿぀-ヿ々ヶ]{1,5}$")
# 空白なしの日本語氏名（例「西宏司」）。2〜6文字の日本語のみ
RE_JP_NAME_NOSP = re.compile(r"^[一-鿿぀-ヿ々ヶ\s　]{2,6}$")
# 日本語（漢字/ひらがな/カタカナ）を1文字でも含むか
RE_HAS_JP = re.compile(r"[一-鿿぀-ヿ]")


def _normalize_phone(s: str) -> str:
    """全角を半角に寄せ、区切りをハイフンに整える"""
    s = s.strip()
    z = "０１２３４５６７８９－（）"
    h = "0123456789-()"
    s = s.translate(str.maketrans(z, h))
    return s


def extract_phones(line: str):
    """1行から (種別, 番号) を抽出。同一行のTEL/FAX併記やラベルで種別を判定する。"""
    results = []
    last = 0
    for m in RE_PHONE.finditer(line):
        prefix = line[last:m.start()].lower()
        num = _normalize_phone(m.group(1))
        digits = re.sub(r"\D", "", num)
        if any(k in prefix for k in ["fax", "ファックス", "ｆａｘ"]):
            kind = "fax"
        elif any(k in prefix for k in ["携帯", "mobile", "cell", "ｍｏｂｉｌｅ"]) \
                or digits.startswith(("090", "080", "070")) \
                or digits.startswith(("8190", "8180", "8170")):
            kind = "mobile"
        else:
            kind = "tel"
        results.append((kind, num))
        last = m.end()
    return results


def parse_business_card(text: str) -> dict:
    """OCRした名刺テキストを氏名・会社・役職・連絡先などに振り分ける"""
    raw_lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n")]
    lines = [ln for ln in raw_lines if ln]

    result = {
        "name": "", "company": "", "title": "",
        "tel": "", "mobile": "", "fax": "",
        "email": "", "url": "", "postal": "", "address": "",
    }

    used = set()  # 連絡先として消費済みの行インデックス

    for i, line in enumerate(lines):
        # メール
        if not result["email"]:
            m = RE_EMAIL.search(line)
            if m:
                result["email"] = m.group(0)
                used.add(i)

        # URL（メール行は除外）
        if not result["url"] and "@" not in line:
            m = RE_URL.search(line)
            if m:
                result["url"] = m.group(0)
                used.add(i)

        # 郵便番号
        if not result["postal"]:
            m = RE_POSTAL.search(line)
            if m:
                result["postal"] = m.group(1).replace("－", "-").replace(" ", "")

        # 電話・FAX・携帯（同一行に複数あっても種別ごとに振り分け）
        for kind, num in extract_phones(line):
            if not result[kind]:
                result[kind] = num
            used.add(i)

        # 住所（郵便番号や都道府県を含む行）
        if not result["address"] and (
            RE_POSTAL.search(line) or re.search(r"[都道府県市区町村]", line)
        ):
            # 〒や郵便番号の断片を取り除いて住所本体を残す
            addr = RE_POSTAL.sub("", line)
            addr = re.sub(r"〒", "", addr).strip(" 　:：")
            if addr and not RE_EMAIL.search(addr):
                result["address"] = addr
                used.add(i)

    # 会社名（最初に見つかった組織キーワード行）
    for i, line in enumerate(lines):
        if any(k in line for k in ORG_KEYWORDS):
            result["company"] = line
            used.add(i)
            break

    # 役職（役職キーワードを含む行）。役職と氏名が同一行なら分離する
    for i, line in enumerate(lines):
        if i in used:
            continue
        matched = [k for k in TITLE_KEYWORDS if k in line]
        if matched:
            kw = max(matched, key=len)  # 最長一致の役職語
            without = line.replace(kw, " ").strip(" 　・/|｜")
            # 役職を除いた残りが氏名らしければ氏名として分離
            if without and RE_JP_NAME.match(without) and not result["name"]:
                result["name"] = without
                result["title"] = kw
            else:
                result["title"] = line
            used.add(i)
            break

    # 氏名（未使用の行から推定）
    name_candidates = [
        (i, line) for i, line in enumerate(lines)
        if i not in used and not RE_EMAIL.search(line)
        and not RE_PHONE.search(line) and not RE_URL.search(line)
        and line not in TITLE_KEYWORDS
    ]
    # 1) 空白区切りの日本語2語を最優先（例「西 宏司」）
    for i, line in name_candidates:
        if RE_JP_NAME.match(line):
            result["name"] = line
            used.add(i)
            break
    # 2) 空白なしの日本語氏名（例「西宏司」）。役職語そのものは除外
    if not result["name"]:
        for i, line in name_candidates:
            if RE_JP_NAME_NOSP.match(line) and not any(k == line for k in TITLE_KEYWORDS):
                result["name"] = line
                used.add(i)
                break
    # 3) フォールバック：日本語を含む短い行（英字ロゴ等は氏名にしない）
    if not result["name"]:
        for i, line in name_candidates:
            if RE_HAS_JP.search(line) and len(line) <= 12:
                result["name"] = line
                used.add(i)
                break

    return result


def _vcard_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_vcard(data: dict) -> str:
    """構造化データから vCard 3.0 を生成（iOSの連絡先で取り込み可能）"""
    name = data.get("name", "").strip()
    name_alt = data.get("name_alt", "").strip()
    # 空白区切りなら 姓・名 に分割（日本語名は「姓 名」が一般的）
    parts = re.split(r"[\s　]+", name) if name else []
    family = parts[0] if parts else ""
    given = parts[1] if len(parts) > 1 else ""

    # 表示名（FN）。別言語の氏名があれば併記して両方を残す（例「山田 太郎 (Taro Yamada)」）
    display = name or data.get("company", "")
    if name_alt and name_alt != name:
        display = f"{display} ({name_alt})" if display else name_alt

    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    lines.append(f"N:{_vcard_escape(family)};{_vcard_escape(given)};;;")
    lines.append(f"FN:{_vcard_escape(display)}")
    # 別言語の氏名はニックネームにも入れて、検索・参照できるようにする
    if name_alt and name_alt != name:
        lines.append(f"NICKNAME:{_vcard_escape(name_alt)}")
    if data.get("company"):
        lines.append(f"ORG:{_vcard_escape(data['company'])}")
    if data.get("title"):
        lines.append(f"TITLE:{_vcard_escape(data['title'])}")
    if data.get("tel"):
        lines.append(f"TEL;TYPE=WORK,VOICE:{data['tel']}")
    if data.get("mobile"):
        lines.append(f"TEL;TYPE=CELL,VOICE:{data['mobile']}")
    if data.get("fax"):
        lines.append(f"TEL;TYPE=WORK,FAX:{data['fax']}")
    if data.get("email"):
        lines.append(f"EMAIL;TYPE=WORK:{data['email']}")
    if data.get("url"):
        lines.append(f"URL:{data['url']}")
    if data.get("address") or data.get("postal"):
        adr = _vcard_escape(data.get("address", ""))
        postal = _vcard_escape(data.get("postal", ""))
        # ADR: post-office-box;extended;street;locality;region;postal-code;country
        lines.append(f"ADR;TYPE=WORK:;;{adr};;;{postal};")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


# =========================================================
# AI解析（Google Gemini 無料枠）
# 環境変数 GEMINI_API_KEY が設定されていれば、こちらを優先して使う。
# キー未設定やAPI失敗時は、上のルール解析へ自動フォールバックする。
# =========================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

GEMINI_PROMPT = (
    "あなたは名刺データの抽出器です。次のテキストは1枚の名刺をOCRしたもので、"
    "改行の順序や向き（縦書き・回転）が乱れていることがあります。"
    "ここから人物1名分の情報を読み取り、指定キーのJSONだけを返してください。\n"
    "- name: 人物の氏名（主表記）。会社名・ロゴ・部署・役職・キャッチコピーは絶対に入れない。"
    "姓名の間は半角スペース1つにする。"
    "名刺に氏名が日本語と英語（ローマ字）の両方で併記されている場合は、"
    "日本語（漢字・かな・カタカナ）の表記を name に入れる。日本語表記が無ければ英語表記を入れる。\n"
    "- name_alt: 同一人物の別言語の氏名表記。氏名が2言語で併記されている場合のみ、"
    "name に入れなかったもう一方（多くは英語・ローマ字）を入れる。"
    "片方の言語しか無い場合は空文字 \"\" にする。姓名の間は半角スペース1つにする。\n"
    "- company: 会社・組織名（株式会社/合同会社/大学/法人など）。\n"
    "- title: 役職・肩書き（部長/代表/教授/CEO/Founder など）。\n"
    "- tel: 固定電話、mobile: 携帯電話、fax: FAX。市外局番から、半角でハイフン区切りに整形。\n"
    "- email, url, postal（郵便番号 例 123-4567）, address（住所）。\n"
    "わからない項目は空文字 \"\" にする。推測で創作しない。\n\n"
    "OCRテキスト:\n"
)


def parse_with_gemini(text: str):
    """Gemini で名刺テキストを解析。成功すれば dict、失敗時は None を返す。"""
    if not GEMINI_API_KEY:
        return None

    body = {
        "contents": [{"parts": [{"text": GEMINI_PROMPT + text}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {f: {"type": "string"} for f in CARD_FIELDS},
            },
        },
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        raw = payload["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw)
    except Exception as e:  # ネットワーク/レート/形式エラーはフォールバック
        print("Gemini解析エラー:", e)
        return None

    result = {f: "" for f in CARD_FIELDS}
    for f in CARD_FIELDS:
        v = parsed.get(f, "")
        result[f] = v.strip() if isinstance(v, str) else (str(v) if v else "")
    return result


@app.post("/parse_card", operation_id="parseBusinessCard")
def parse_card(text: str = Form(...), format: str = Form("json")):
    """名刺OCRテキストを解析して構造化データ／vCardを返す。

    - text: iOSショートカットの「画像からテキストを抽出」で得た生テキスト
    - format: "json"（既定）/ "vcard" / "both"
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is empty")

    # AI解析を優先し、ダメならルール解析にフォールバック
    data = parse_with_gemini(text)
    engine = "gemini"
    if data is None:
        data = parse_business_card(text)
        engine = "rules"
    vcard = build_vcard(data)

    if format == "vcard":
        return PlainTextResponse(content=vcard, media_type="text/vcard; charset=utf-8")
    if format == "both":
        return {"data": data, "vcard": vcard, "engine": engine}
    return {"data": data, "engine": engine}
