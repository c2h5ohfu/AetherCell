# agent/agent_runner.py

from typing_extensions import Dict, Any, Optional, List
import aiosqlite
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent.cell_agent import cell_agent

load_dotenv()

# --- Checkpointer Initialization ---
# 使用 AsyncSqliteSaver
DB_PATH = "sql_app.db"  # 数据库文件路径
try:
    # 使用 acreate 异步创建或连接数据库
    memory = AsyncSqliteSaver(conn=aiosqlite.connect(DB_PATH))
except Exception as e:
    raise  # 初始化失败则抛出


# --- Run Function (非流式) ---
async def run_supervisor(session_id: str, user_input_message: BaseMessage, user_info: Dict[str, Any]) -> Dict[str, Any]:
    """ 异步运行 Supervisor 图, 并返回最终状态。"""
    checkpointer_type_name = type(memory).__name__
    user_info['session_id'] = session_id  # 确保 session_id 在 user_info 中
    inputs: Dict[str, Any] = {"messages": [user_input_message]}
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 50}
    final_state: Dict[str, Any] = {}
    try:
        final_state = await cell_agent.ainvoke(inputs, config=config)
    except Exception as e:
        final_state = {"error": str(e), "messages": []}
    return final_state


def get_last_ai_message_content(final_state: Dict[str, Any]) -> Optional[str]:
    messages = final_state.get("messages", [])
    if not messages: return None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage): return msg.content
    return None
