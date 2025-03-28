from langchain_community.document_loaders import CSVLoader,UnstructuredExcelLoader


def load_documents(file_path: str):
    if file_path.endswith('.csv'):
        loader = CSVLoader(file_path)
    elif file_path.endswith(('.xls', '.xlsx')):
        loader = UnstructuredExcelLoader(file_path)
    else:
        raise ValueError("Unsupported file type")

    return loader.load()

