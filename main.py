from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class LogInput(BaseModel):
    entry_type: str
    content: str

@app.post("/log")
def add_log(log: LogInput):
    return {
        "yaml": f"entry_type: {log.entry_type}\ncontent: {log.content}",
        "advice": "『主食・主菜・副菜をそろえよう』"
    }
