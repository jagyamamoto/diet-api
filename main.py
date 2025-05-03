# main.py  ---------------------------------------------------------------
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import io, zipfile, xml.etree.ElementTree as ET
from typing import Optional
from PIL import Image
import piexif

app = FastAPI(title="Diet Assistant API")

# CORS（必要ならドメインを限定してください）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 共通レスポンス ---------- #
class LogOutput(BaseModel):
    yaml: str
    advice: str

# ---------------------------------------------------------------------- #
# 1) /log  テキスト入力
# ---------------------------------------------------------------------- #
class LogInput(BaseModel):
    entry_type: str
    content: str

@app.post("/log", response_model=LogOutput)
def log_text(input: LogInput):
    yaml = f"entry_type: {input.entry_type}\ncontent: {input.content}"
    return {
        "yaml": yaml,
        "advice": "『主食・主菜・副菜をそろえよう』"
    }

# ---------------------------------------------------------------------- #
# 2) /photo_log  Exif 解析
# ---------------------------------------------------------------------- #
@app.post("/photo_log", response_model=LogOutput)
async def photo_log(file: UploadFile = File(...)):
    try:
        img_bytes = await file.read()
        img = Image.open(io.BytesIO(img_bytes))
        exif_data = img.info.get("exif")

        if not exif_data:
            return {
                "yaml": "entry_type: photo\nerror: Exif情報がありません",
                "advice": "Exifが無いため撮影時間を特定できませんでした"
            }

        exif_dict = piexif.load(exif_data)
        dt_bytes: Optional[bytes] = exif_dict["Exif"].get(piexif.ExifIFD.DateTimeOriginal)
        dt_str = dt_bytes.decode("utf-8") if dt_bytes else "Exifに日時がありません"

        yaml = f"entry_type: photo\nfilename: {file.filename}\nphoto_taken: \"{dt_str}\""
        return {
            "yaml": yaml,
            "advice": "『撮影時間＝食事時間としてログしました』"
        }
    except Exception as e:
        return {
            "yaml": "entry_type: photo\nerror: Exif解析に失敗",
            "advice": f"エラー: {str(e)}"
        }

# ---------------------------------------------------------------------- #
# 3) /daily_summary  指定日の統括（簡易版）
# ---------------------------------------------------------------------- #
class SummaryInput(BaseModel):
    date: str  # YYYY-MM-DD

@app.post("/daily_summary", response_model=LogOutput)
def daily_summary(input: SummaryInput):
    yaml = (
        f"summary_date: {input.date}\n"
        f"meals: 3\n"
        f"steps: 7200\n"
        f"exercise_minutes: 25"
    )
    advice = f"『{input.date} はよく動けています。水分を多めにとりましょう』"
    return {"yaml": yaml, "advice": advice}

# ---------------------------------------------------------------------- #
# 4) /apple_health_zip  ヘルスケア ZIP アップロード
# ---------------------------------------------------------------------- #
@app.post("/apple_health_zip", response_model=LogOutput)
async def apple_health_zip(file: UploadFile = File(...)):
    """iPhone ヘルスケアの export.zip を受け取り、歩数合計を抽出する"""
    try:
        raw = await file.read()

        # -- ZIP を開き、export.xml を読み込み --
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml_bytes = z.read("apple_health_export/export.xml")

        # -- 逐次パース（大容量でもOK） --
        steps_total = 0
        for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
            if elem.tag.endswith("Record") and \
               elem.attrib.get("type") == "HKQuantityTypeIdentifierStepCount":
                steps_total += int(float(elem.attrib["value"]))
            elem.clear()  # メモリ節約

        jst = timezone(timedelta(hours=+9))
        today = datetime.now(jst).strftime("%Y-%m-%d")

        yaml = (
            f"date: {today}\n"
            f"apple_health:\n"
            f"  steps: {steps_total}"
        )
        advice = "『目標 8000 歩にあと少し！階段を選んで達成しましょう』"
        return {"yaml": yaml, "advice": advice}

    except Exception as e:
        return {
            "yaml": "apple_health: error",
            "advice": f"ZIP解析エラー: {str(e)}"
        }

# ---------------------------------------------------------------------- #
# ルート確認用（オプション）
# ---------------------------------------------------------------------- #
@app.get("/")
def root():
    return {"status": "ok", "message": "Diet Assistant API is running"}
