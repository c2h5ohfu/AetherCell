
from langchain_core.tools import tool

import pandas as pd
from langchain_community.document_loaders import CSVLoader
from langchain_core.tools import tool, create_retriever_tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

from test.agent_with_rag.agent.config import embeddings

vectorstore = Chroma(
    collection_name="example_collection",
    embedding_function=embeddings,
    persist_directory="./chroma_langchain_db"
)

text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    chunk_size=100, chunk_overlap=50
)

@tool
def readfile(file_path: str):

    "读取文件"
    if file_path.endswith('.csv'):
        loader = CSVLoader(file_path)
    elif file_path.endswith('.xlsx'):
        # 转换Excel为临时CSV
        df = pd.read_excel(file_path)
        temp_csv_path = "temp.csv"
        df.to_csv(temp_csv_path, index=False)
        loader = CSVLoader(temp_csv_path)
    documents = loader.load()  # 先加载文档
    doc_splits = text_splitter.split_documents(documents)  # 再分割
    _ = vectorstore.add_documents(documents=doc_splits)
    return loader.load()


if __name__ == '__main__':
    readfile.invoke("/home/lreuxcu/AetherCell/src/resource/Europe_GDP.csv")