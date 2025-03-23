from langchain_core.tools import tool, create_retriever_tool

from test.agent_with_rag.tools.loader import vectorstore


@tool
def retriever(docs):
    """
    搜索并返回与用户提问相关文件的信息
    """

    retriever = vectorstore.as_retriever()
    return create_retriever_tool(
        retriever,
        "retrieve",
        "搜索并返回与用户提问相关文件的信息",
    )