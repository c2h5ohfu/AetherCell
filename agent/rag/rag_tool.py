from langchain_core.tools import tool

from langchain_core.documents import Document
from typing_extensions import List, Optional
from .vector_store import query_vector_store

from agent.graph_state import AgentState


@tool
async def retrieve_documents(query: str, state: AgentState) -> str:
    """
    根据用户查询从向量存储中检索相关文档片段。
    如果状态中包含用户信息，则会同时检索该用户的私有文档和公共文档。
    使用此工具来回答关于特定文件内容或需要背景知识的问题。
    """
    print(f"--- Calling RAG Tool: retrieve_documents ---")
    print(f"Query: {query}")

    user_info = state.get("user_info")
    user_id: Optional[int] = None

    if user_info and isinstance(user_info, dict):
        # 假设 user_info 字典中包含 'user_id' 键
        user_id = user_info.get("user_id")

    print(f"Retrieving documents for user_id: {user_id}")

    # 调用向量存储查询函数，检索 top 3 相关文档
    documents: List[Document] = await query_vector_store(query = query, user_id = user_id, k=3)

    if not documents:
        print("No documents found.")
        # 返回更自然的回复给 LLM
        return "I couldn't find any relevant documents in the knowledge base regarding that query."

    # 格式化检索到的文档内容，以便 LLM 理解
    formatted_docs = "\n\n---\n\n".join([
        f"Source: {doc.metadata.get('source', 'Unknown')}, Chunk Index: {doc.metadata.get('chunk_index', 'N/A')}\n"
        f"Content: {doc.page_content}"
        for doc in documents
    ])

    print(f"Retrieved {len(documents)} documents.")
    # print(f"Formatted documents for LLM:\n{formatted_docs}") # 调试时可以取消注释

    # 返回给 LLM 的内容应包含上下文信息
    return f"Based on the query '{query}', here are the relevant excerpts from the knowledge base:\n\n{formatted_docs}"
