from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from datetime import datetime
import piexif
from PIL import Image
import io

app = FastAPI()

# ---------- モデル定義 ----------
class LogInput(BaseModel):
    entry_type: str
    content: str

class LogOutput(BaseModel):
    yaml: str
    advice: str

class SummaryInput(BaseModel):
    date: str  # YYYY-MM-DD

class AppleHealthInput(BaseModel):
    health_data_json: str

# ---------- /log ----------
@app.post("/log", response_model=LogOutput)
def log(input: LogInput):
    yaml = f"entry_type: {input.entry_type}\ncontent: {input.content}"
    return {
        "yaml": yaml,
        "advice": "『主食・主菜・副菜をそろえよう』"
    }

# ---------- /photo_log ----------
@app.post("/photo_log", response_model=LogOutput)
async def photo_log(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        exif_data = image.info.get('exif')

        if exif_data:
            exif_dict = piexif.load(exif_data)
            date_str = exif_dict['Exif'].get(piexif.ExifIFD.DateTimeOriginal)
            if date_str:
                date = date_str.decode('utf-8')
            else:
                date = "Exifに日時がありません"
        else:
            date = "Exif情報がありません"

        yaml = f"entry_type: photo\nphoto_taken: {date}\nfilename: {file.filename}"
        return {
            "yaml": yaml,
            "advice": "『撮影時間に近い時間帯の食事とみなします』"
        }

    except Exception as e:
        return {
            "yaml": "entry_type: photo\nerror: Exif情報の解析に失敗しました",
            "advice": f"エラー内容: {str(e)}"
        }

# ---------- /daily_summary ----------
@app.post("/daily_summary", response_model=LogOutput)
def daily_summary(input: SummaryInput):
    return {
        "yaml": f"summary_date: {input.date}\nmeals: 3\nsteps: 7200\nexercise_minutes: 25",
        "advice": f"『{input.date} はよく動けています。水分を多めにとりましょう』"
    }

# ---------- /apple_health ----------
@app.post("/apple_health", response_model=LogOutput)
def apple_health(input: AppleHealthInput):
    return {
        "yaml": f"apple_health:\n  raw_json: |\n    {input.health_data_json}",
        "advice": "『心拍数に注意。睡眠リズムを整えましょう』"
    }
