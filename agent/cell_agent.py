# agent/cell_agent.py
import os
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent.rag.retrieval_tools import retrieval_tools
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from agent.tools.calculator_tools import calculator_tools

# 全局变量存储 agent 实例
_agent_instance = None
_db_connection = None

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3")  # Ollama 模型名称
DB_PATH = "cell_agent.db"  # 数据库文件路径
all_tools = retrieval_tools + calculator_tools  # 合并所有需要的工具


def get_agent():
    """获取全局 agent 单例实例"""
    global _agent_instance, _db_connection

    if _agent_instance is None:
        # 初始化数据库连接
        _db_connection = aiosqlite.connect(DB_PATH)
        memory = AsyncSqliteSaver(conn=_db_connection)

        llm = ChatOllama(model=OLLAMA_MODEL, extract_reasoning=True)

        _agent_instance = create_react_agent(
            model=llm,
            tools=all_tools,
            name="cell_expert",
            checkpointer=memory,
            prompt=(
                "你是一个善于解决问题的agent\n"
                "当用户想你提问一个问题的时候，你首先要调用工具检索一下知识库，"
                "如果知识库中存在答案，返回给用户，如果没有答案，自己生成\n"
                "如果用户仅仅是简单的打招呼之类，你可以直接回复"
            )
        )

    return _agent_instance


async def close_db_connection():
    """关闭数据库连接"""
    global _db_connection
    if _db_connection:
        await _db_connection.close()
        _db_connection = None
        print("数据库连接已关闭")