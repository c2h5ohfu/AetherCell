# agent/graph_state.py
from typing_extensions import TypedDict, Annotated, List, Optional, Dict, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    Defines the state for the LangGraph multi-agent system.

    Attributes:
        messages: List of messages, managed by add_messages.
        user_info: Optional dictionary containing user information.
        next: The name of the next agent node to execute or END.
    """
    messages: Annotated[List[BaseMessage], add_messages]
    user_info: Optional[Dict[str, Any]]
    # 'next' will store the routing decision from the supervisor
    # next: str
