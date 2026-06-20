from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import PlainTextResponse
from typing import Optional
from datetime import datetime, timedelta
import os, uuid, yaml, re
import dropbox

# Dropboxアクセストークン（Renderの環境変数に設定しておくこと）
DROPBOX_TOKEN = os.getenv("DROPBOX_TOKEN")
if not DROPBOX_TOKEN:
    raise RuntimeError("Dropbox access token not set in environment variable 'DROPBOX_TOKEN'.")

dbx = dropbox.Dropbox(DROPBOX_TOKEN)

app = FastAPI(
    title="Diet API",
    version="1.0.0",
    servers=[
        {"url": "https://diet-api-ebhn.onrender.com", "description": "Production"}
    ]
)

# Render の Persistent Disk 対応パス
BASE_DIR = "/persistent/data"
os.makedirs(BASE_DIR, exist_ok=True)

# 1. ランダムユーザーID発行
def generate_user_id():
    return f"user_{uuid.uuid4().hex[:8]}"

# Dropboxにファイルアップロードする関数
def save_to_dropbox(user_id: str, filename: str, content: str):
    try:
        dbx.files_upload(
            content.encode("utf-8"),
            f"/{user_id}/{filename}",
            mode=dropbox.files.WriteMode("overwrite")
        )
    except Exception as e:
        print("Dropbox保存エラー:", e)

@app.post("/register_user", operation_id="registerUser")
def register_user():
    user_id = generate_user_id()
    user_path = os.path.join(BASE_DIR, user_id)
    os.makedirs(user_path, exist_ok=True)
    return {"user_id": user_id}

@app.get("/current_user")
def current_user(user_id: str):
    user_path = os.path.join(BASE_DIR, user_id)
    if os.path.exists(user_path):
        return {"user_id": user_id, "status": "exists"}
    return {"error": "user_id not found"}

@app.post("/photo_log")
def photo_log(user_id: str = Form(...), file: UploadFile = File(...)):
    post_time = datetime.now()
    timestamp = post_time.strftime("%Y%m%dT%H%M")
    filename = f"{timestamp}.yaml"
    user_dir = os.path.join(BASE_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)

    data = {
        "entry_type": "photo",
        "filename": file.filename,
        "photo_taken": post_time.strftime("%Y-%m-%d %H:%M:%S"),
        "posted_time": post_time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "original"
    }

    # ローカル保存
    local_path = os.path.join(user_dir, filename)
    with open(local_path, "w") as f:
        yaml.dump(data, f, allow_unicode=True)

    # Dropbox保存
    save_to_dropbox(user_id, filename, yaml.dump(data, allow_unicode=True))

    return {"yaml": yaml.dump(data), "advice": "『投稿時間を食事時間として登録しました』"}

@app.post("/update_log")
def update_log(user_id: str = Form(...), timestamp: str = Form(...), content: str = Form(...)):
    user_dir = os.path.join(BASE_DIR, user_id)
    if not os.path.exists(user_dir):
        raise HTTPException(status_code=404, detail="user not found")

    filename = f"{timestamp}.updated.yaml"

    # YAML整形＆バリデーション処理
    cleaned = content.strip()
    try:
        data = yaml.safe_load(cleaned)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML形式エラー: {str(e)}")

    data["version"] = "updated"

    # ローカル保存
    local_path = os.path.join(user_dir, filename)
    with open(local_path, "w") as f:
        yaml.dump(data, f, allow_unicode=True)

    # Dropbox保存
    save_to_dropbox(user_id, filename, yaml.dump(data, allow_unicode=True))

    return {"yaml": yaml.dump(data), "advice": "『修正内容を更新版として保存しました』"}

@app.post("/daily_summary")
def daily_summary(user_id: str = Form(...), date: str = Form(...)):
    try:
        base_date = datetime.strptime(date, "%Y-%m-%d")
    except:
        raise HTTPException(status_code=400, detail="Invalid date format")

    start = base_date.replace(hour=2)
    end = start + timedelta(hours=24)
    user_dir = os.path.join(BASE_DIR, user_id)
    if not os.path.exists(user_dir):
        raise HTTPException(status_code=404, detail="user not found")

    summary = []
    for fname in sorted(os.listdir(user_dir)):
        if fname.endswith(".yaml"):
            timestamp = fname[:13]
            try:
                dt = datetime.strptime(timestamp, "%Y%m%dT%H%M")
            except:
                continue
            if start <= dt < end:
                with open(os.path.join(user_dir, fname)) as f:
                    yml = yaml.safe_load(f)
                    summary.append(yml)

    return {
        "yaml": yaml.dump(summary, allow_unicode=True),
        "advice": f"『{date}のまとめを生成しました（{len(summary)}件）』"
    }

# =========================================================
# 名刺OCR解析（iPhoneショートカットの「画像からテキストを抽出」と連携）
# 撮影とOCRはiOS側で無料実行し、生テキストをここに送って構造化する
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
# 名前らしい行（漢字/かな主体で空白区切りの2語、または短い日本語名）
RE_JP_NAME = re.compile(r"^[一-鿿぀-ヿ々ヶ]{1,5}[\s　]+[一-鿿぀-ヿ々ヶ]{1,5}$")


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
            # 〒や電話の断片を取り除いて住所本体を残す
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

    # 氏名（未使用の行から、空白区切りの日本語2語を最優先）
    name_candidates = [
        (i, line) for i, line in enumerate(lines)
        if i not in used and not RE_EMAIL.search(line)
        and not RE_PHONE.search(line) and not RE_URL.search(line)
    ]
    for i, line in name_candidates:
        if RE_JP_NAME.match(line):
            result["name"] = line
            used.add(i)
            break
    # 見つからなければ、会社名より上の短い行を氏名とみなす
    if not result["name"] and name_candidates:
        i, line = name_candidates[0]
        if len(line) <= 20:
            result["name"] = line

    return result


def _vcard_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_vcard(data: dict) -> str:
    """構造化データから vCard 3.0 を生成（iOSの連絡先で取り込み可能）"""
    name = data.get("name", "").strip()
    # 空白区切りなら 姓・名 に分割（日本語名は「姓 名」が一般的）
    parts = re.split(r"[\s　]+", name) if name else []
    family = parts[0] if parts else ""
    given = parts[1] if len(parts) > 1 else ""

    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    lines.append(f"N:{_vcard_escape(family)};{_vcard_escape(given)};;;")
    lines.append(f"FN:{_vcard_escape(name or data.get('company',''))}")
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


@app.post("/parse_card", operation_id="parseBusinessCard")
def parse_card(text: str = Form(...), format: str = Form("json")):
    """名刺OCRテキストを解析して構造化データ／vCardを返す。

    - text: iOSショートカットの「画像からテキストを抽出」で得た生テキスト
    - format: "json"（既定）/ "vcard" / "both"
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is empty")

    data = parse_business_card(text)
    vcard = build_vcard(data)

    if format == "vcard":
        return PlainTextResponse(content=vcard, media_type="text/vcard; charset=utf-8")
    if format == "both":
        return {"data": data, "vcard": vcard}
    return {"data": data}
