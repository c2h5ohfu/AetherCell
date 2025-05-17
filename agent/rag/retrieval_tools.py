# agent/rag/retrieval_tools.py
# 解释：此文件包含用于从向量数据库检索文档的工具。
# 这些工具区分公共知识库和特定于当前会话的知识。

from langchain_core.tools import tool
from langchain_core.documents import Document
from typing import List, Optional, Any, Dict  # 确保 Dict 被导入
import logging

# 根据您的项目结构，确保导入路径正确
from agent.rag.vector_store import query_vector_store  # 假设 vector_store.py 在同一个 rag 包下
from agent.graph_state import AgentState  # 假设 graph_state.py 在 agent 包的根目录

logger = logging.getLogger(__name__)


@tool
async def retrieve_public_knowledge(query: str) -> str:
    """
    根据用户查询从 **公共共享知识库** 中检索相关文档片段。
    用于回答一般性知识问题或引用上传到共享存储库的文档。
    不要用于仅上传到当前会话的文件。
    """
    logger.info(f"--- 工具调用: retrieve_public_knowledge ---")
    logger.info(f"查询内容: {query}")

    # 调用 query_vector_store 时不带 session_id 以搜索公共块 (全局知识)
    documents: List[Document] = await query_vector_store(query=query, k=3, session_id=None)

    if not documents:
        logger.info("在公共知识库中未找到相关文档。")
        return "我在公共知识库中找不到与该查询相关的文档。"

    # 格式化结果
    formatted_docs = "\n\n---\n\n".join([
        f"来源: {doc.metadata.get('source', '未知')}, "
        # f"块索引: {doc.metadata.get('chunk_index', 'N/A')}, " # 可选
        f"相关度得分: {doc.metadata.get('retrieval_score', 'N/A'):.4f}\n"  # 显示得分
        f"内容: {doc.page_content}"
        for doc in documents
    ])

    logger.info(f"检索到 {len(documents)} 个公共文档。")
    return f"根据您的查询 '{query}'，以下是从公共知识库中检索到的相关摘要:\n\n{formatted_docs}"


@tool
async def retrieve_session_knowledge(query: str, state: AgentState) -> str:
    """
    根据用户查询从 **当前会话** 中专门上传的文件中检索相关文档片段。
    当用户询问他们刚刚在此聊天中上传的文件，或提及特定于此会话文档的上下文时使用此工具。
    """
    logger.info(f"--- 工具调用: retrieve_session_knowledge ---")
    logger.info(f"查询内容: {query}")

    # 从状态中提取 session_id
    user_info: Optional[Dict[str, Any]] = state.get("user_info")
    session_id: Optional[str] = None
    if user_info and isinstance(user_info, dict):
        session_id = user_info.get("session_id")  # 确保 user_info 中包含 session_id

    if not session_id:
        logger.error("在状态中未找到用于 retrieve_session_knowledge 工具的 Session ID。")
        return "错误：没有会话 ID 无法检索特定于会话的知识。"

    logger.info(f"正在检索会话 ID: {session_id} 的文档")

    # 调用 query_vector_store 并传入 session_id 以过滤结果
    documents: List[Document] = await query_vector_store(query=query, k=3, session_id=session_id)

    if not documents:
        logger.info(f"在会话 {session_id} 的上下文中未找到相关文档。")
        return f"我在本次会话 (ID: {session_id}) 上传的文件中找不到与该查询相关的文档。"

    # 格式化结果
    formatted_docs = "\n\n---\n\n".join([
        f"来源 (会话文件): {doc.metadata.get('source', '未知')}, "
        # f"块索引: {doc.metadata.get('chunk_index', 'N/A')}, " # 可选
        f"相关度得分: {doc.metadata.get('retrieval_score', 'N/A'):.4f}\n"  # 显示得分
        f"内容: {doc.page_content}"
        for doc in documents
    ])

    logger.info(f"从会话 {session_id} 检索到 {len(documents)} 个文档。")
    return f"根据您的查询 '{query}'，以下是从先前在此会话 ({session_id}) 中上传的文件中检索到的相关摘要:\n\n{formatted_docs}"


# 将所有文件检索相关的工具放入列表，方便 Agent 使用
# 可以重命名这个列表以反映其内容，例如 retrieval_tools
retrieval_tools = [retrieve_public_knowledge, retrieve_session_knowledge]
