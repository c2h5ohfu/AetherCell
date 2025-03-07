from langchain_community.document_loaders import CSVLoader,UnstructuredExcelLoader

from langchain_core.tools import tool

@tool
def load_documents(file_path: str):
    """当接受的是文件地址时，读取文件"""
    if file_path.endswith('.csv'):
        loader = CSVLoader(file_path)
    elif file_path.endswith(('.xls', '.xlsx')):
        loader = UnstructuredExcelLoader(file_path)
    else:
        raise ValueError("Unsupported file type")

    return loader.load()

