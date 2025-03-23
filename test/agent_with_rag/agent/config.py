from langchain_ollama import ChatOllama
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain.tools.retriever import create_retriever_tool

llm = ChatOllama(model = "qwen2.5:7b")
embeddings = OllamaEmbeddings(model="nomic-embed-text")


