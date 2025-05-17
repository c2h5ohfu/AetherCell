# agent/cell_agent.py
import os

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent.rag.retrieval_tools import retrieval_tools
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from agent.tools.calculator_tools import calculator_tools

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3")  # Ollama 模型名称

llm = ChatOllama(model=OLLAMA_MODEL, extract_reasoning=True)

DB_PATH = "cell_agent.db"  # 数据库文件路径
try:
    memory = AsyncSqliteSaver(conn=aiosqlite.connect(DB_PATH))
except Exception as e:
    raise

all_tools = retrieval_tools + calculator_tools  # 合并所有需要的工具

cell_agent = create_react_agent(model=llm,
                                tools=all_tools,
                                name="cell_expert",
                                checkpointer=memory,
                                prompt=  # "/no_think"  # qwen3官方提供了两种方法来决定是否开启推理模式，enable_thinking的方法langchain并没有封装，因此采用在提示词中利用软开关的方法实现
                                "你是一个善于解决问题的agent"
                                "当用户想你提问一个问题的时候，你首先要调用工具检索一下知识库，如果知识库中存在答案，返回给用户，如果没有答案，自己生成"
                                "如果用户仅仅是简单的打招呼之类，你可以直接回复")
