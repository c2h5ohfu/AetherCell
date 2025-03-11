from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import pandas as pd
from io import BytesIO
from agentDemo import Agent

app = FastAPI()

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 定义数据模型
class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]


class ChatResponse(BaseModel):
    content: str


# 初始化AI代理
@app.on_event("startup")
async def startup_event():
    app.state.agent = Agent()


# 聊天接口
@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        agent = app.state.agent
        messages = [msg.dict() for msg in request.messages]
        response_content = agent.chat(messages)
        return ChatResponse(content=response_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 文件上传接口
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if file.content_type != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        raise HTTPException(400, "仅支持.xlsx文件")

    try:
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))
        summary = f"文件包含 {df.shape[0]} 行 {df.shape[1]} 列\n示例数据:\n{df.head().to_string(index=False)}"
        preview = df.head().to_dict(orient="records")
        return {"summary": summary, "preview": preview}
    except Exception as e:
        raise HTTPException(500, f"文件解析失败: {str(e)}")