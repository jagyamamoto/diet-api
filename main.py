from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime, timedelta
import os, uuid, yaml

app = FastAPI()

BASE_DIR = "data"
os.makedirs(BASE_DIR, exist_ok=True)

# 1. ランダムユーザーID発行
def generate_user_id():
    return f"user_{uuid.uuid4().hex[:8]}"

@app.post("/register_user")
def register_user():
    user_id = generate_user_id()
    user_path = os.path.join(BASE_DIR, user_id)
    os.makedirs(user_path, exist_ok=True)
    return {"user_id": user_id}

# 1a. 現在のユーザーIDを確認
@app.get("/current_user")
def current_user(user_id: str):
    user_path = os.path.join(BASE_DIR, user_id)
    if os.path.exists(user_path):
        return {"user_id": user_id, "status": "exists"}
    return {"error": "user_id not found"}

# 2. 写真投稿（投稿時間 = 食事時間）
@app.post("/photo_log")
def photo_log(user_id: str = Form(...), file: UploadFile = File(...)):
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    
    post_time = datetime.now()
    timestamp = post_time.strftime("%Y%m%dT%H%M")
    filename = f"{timestamp}.yaml"
    user_dir = os.path.join(BASE_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    
    # YAML保存
    data = {
        "entry_type": "photo",
        "filename": file.filename,
        "photo_taken": post_time.strftime("%Y-%m-%d %H:%M:%S"),
        "posted_time": post_time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "original"
    }
    with open(os.path.join(user_dir, filename), "w") as f:
        yaml.dump(data, f, allow_unicode=True)

    return {"yaml": yaml.dump(data), "advice": "『投稿時間を食事時間として登録しました』"}

# 3. 修正投稿（更新版として保存）
@app.post("/update_log")
def update_log(user_id: str = Form(...), timestamp: str = Form(...), content: str = Form(...)):
    user_dir = os.path.join(BASE_DIR, user_id)
    if not os.path.exists(user_dir):
        raise HTTPException(status_code=404, detail="user not found")
    
    filename = f"{timestamp}.updated.yaml"
    data = yaml.safe_load(content)
    data["version"] = "updated"

    with open(os.path.join(user_dir, filename), "w") as f:
        yaml.dump(data, f, allow_unicode=True)

    return {"yaml": yaml.dump(data), "advice": "『修正内容を更新版として保存しました』"}

# 4. 1日まとめ
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
            timestamp = fname[:13]  # YYYYMMDDTHHMM
            try:
                dt = datetime.strptime(timestamp, "%Y%m%dT%H%M")
            except:
                continue
            if start <= dt < end:
                with open(os.path.join(user_dir, fname)) as f:
                    yml = yaml.safe_load(f)
                    summary.append(yml)

    return {"yaml": yaml.dump(summary, allow_unicode=True), "advice": f"『{date}のまとめを生成しました（{len(summary)}件）』"}
