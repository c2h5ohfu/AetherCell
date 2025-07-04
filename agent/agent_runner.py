# agent/agent_runner.py

from typing_extensions import Dict, Any, Optional, List
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from agent.cell_agent import get_agent  # 导入获取 agent 的方法

load_dotenv()


# --- Run Function (非流式) ---
async def run_supervisor(session_id: str, user_input_message: BaseMessage, user_info: Dict[str, Any]) -> Dict[str, Any]:
    """异步运行 Supervisor 图, 并返回最终状态"""
    # 获取全局 agent 实例
    cell_agent = get_agent()

    user_info['session_id'] = session_id
    inputs: Dict[str, Any] = {"messages": [user_input_message]}
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 50}

    try:
        final_state = await cell_agent.ainvoke(inputs, config=config)
    except Exception as e:
        final_state = {"error": str(e), "messages": []}

    return final_state


def get_last_ai_message_content(final_state: Dict[str, Any]) -> Optional[str]:
    messages = final_state.get("messages", [])
    if not messages:
        return None

    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content
    return None