from typing import List, Dict, Union
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph


class Agent:
    def __init__(self):
        # 初始化模型和提示模板
        self.model = OllamaLLM(model="qwen2.5:7b")
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", "你是一个擅长解决问题的AI"),
            MessagesPlaceholder(variable_name="messages"),
        ])

        # 构建工作流
        self.workflow = StateGraph(state_schema=MessagesState)
        self.workflow.add_node("model", self.call_model)
        self.workflow.add_edge(START, "model")

        # 初始化内存和配置
        self.memory = MemorySaver()
        self.app_workflow = self.workflow.compile(checkpointer=self.memory)
        self.config = {"configurable": {"thread_id": "abc123"}}

    def call_model(self, state: dict):
        """处理消息的模型调用"""
        prompt = self.prompt_template.invoke(state)
        response = self.model.invoke(prompt)
        return {"messages": [AIMessage(content=response)]}

    def process_messages(self, messages: List[Dict]) -> List[Union[HumanMessage, AIMessage]]:
        """将字典消息转换为LangChain消息对象"""
        converted = []
        for msg in messages:
            if msg["role"] == "user":
                converted.append(HumanMessage(content=msg["content"]))
            else:
                converted.append(AIMessage(content=msg["content"]))
        return converted

    def chat(self, messages: List[Dict]) -> str:
        """处理聊天请求"""
        langchain_messages = self.process_messages(messages)
        output = self.app_workflow.invoke(
            {"messages": langchain_messages},
            self.config
        )
        return output["messages"][-1].content