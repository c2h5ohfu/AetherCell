from langchain_core.tools import tool

@tool
def search(query: str):
    """Call to surf the web."""
    # This is a placeholder, but don't tell the LLM that...
    if "济南" in query.lower():
        return "工具测试"
    return "工具测试成功"