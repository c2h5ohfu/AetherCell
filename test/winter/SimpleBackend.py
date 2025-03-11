from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
import base64

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph

app = FastAPI()

# 允许所有来源访问（根据实际需求调整）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 定义数据模型
class Message(BaseModel):
    role: str  # "user" 或 "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]


class ChatResponse(BaseModel):
    content: str


class PlotRequest(BaseModel):
    data: List[Dict]  # 修改为列表字典
    plot_type: str  # "bar" 或 "line"


class PlotResponse(BaseModel):
    image_base64: str


# 1. 初始化模型
@app.on_event("startup")
async def startup_event():
    global model, prompt_template, workflow, memory, app_workflow, config
    model = OllamaLLM(model="qwen2.5:7b")

    prompt_template = ChatPromptTemplate.from_messages(
        [
            ("system", "你是一个擅长解决问题的AI"),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    workflow = StateGraph(state_schema=MessagesState)

    def call_model(state: dict):
        messages = state.get("messages", [])
        prompt = prompt_template.invoke(state)
        response = model.invoke(prompt)
        return {"messages": [AIMessage(content=response)]}

    workflow.add_edge(START, "model")
    workflow.add_node("model", call_model)

    memory = MemorySaver()
    app_workflow = workflow.compile(checkpointer=memory)

    config = {"configurable": {"thread_id": "abc123"}}


# 2. 聊天接口
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    try:
        output = app_workflow.invoke({"messages": messages}, config)
        response_message = output["messages"][-1]
        return ChatResponse(content=response_message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3. 文件上传与解析接口
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if file.content_type not in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")

    try:
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))
        summary = f"文件包含 {df.shape[0]} 行和 {df.shape[1]} 列。数据的一部分：\n{df.head().to_string(index=False)}"
        data_preview = df.head().to_dict(orient='records')
        return {"summary": summary, "data_preview": data_preview}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法解析Excel文件: {e}")


# 4. 图表生成接口
@app.post("/generate_plot", response_model=PlotResponse)
async def generate_plot(request: PlotRequest):
    data = request.data
    plot_type = request.plot_type.lower()

    try:
        df = pd.DataFrame(data)

        plt.figure(figsize=(12, 8))
        plt.style.use('ggplot')  # 使用预定义的样式

        if plot_type == "bar":
            df.plot(kind="bar", x=df.columns[0], y=df.columns[1:], color='skyblue')
            plt.title("柱状图", fontsize=16, color='navy')
        elif plot_type == "line":
            df.plot(kind="line", x=df.columns[0], y=df.columns[1:], marker='o', linestyle='-', color='green')
            plt.title("折线图", fontsize=16, color='navy')
        else:
            raise HTTPException(status_code=400, detail="不支持的图表类型")

        plt.xlabel(df.columns[0], fontsize=14)
        plt.ylabel("数值", fontsize=14)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.tight_layout()

        buf = BytesIO()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)

        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        return PlotResponse(image_base64=img_base64)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成图表失败: {e}")
