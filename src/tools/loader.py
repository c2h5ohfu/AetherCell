
from langchain_core.tools import tool
import pandas as pd

@tool
def load_documents(file_path):
    """
    使用pandas读取Excel或CSV文件，并返回一个DataFrame对象。

    返回:
        pd.DataFrame: 包含文件数据的DataFrame对象。
    """
    try:
        # 根据文件扩展名判断文件类型
        if file_path.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path)
        elif file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            raise ValueError("不支持的文件格式。仅支持Excel (.xlsx, .xls) 和 CSV (.csv) 文件。")
        return df
    except Exception as e:
        print(f"加载文件时出错: {e}")
        return None
