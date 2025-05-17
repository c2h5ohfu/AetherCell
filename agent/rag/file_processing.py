# agent/rag/file_processing.py
import asyncio
import os
import json
import logging
from langchain_core.documents import Document
from langchain_community.document_loaders import (  # 导入新的加载器
    UnstructuredExcelLoader,
    CSVLoader,
    PyPDFLoader,  # 用于 PDF
    TextLoader,  # 用于 TXT
    UnstructuredMarkdownLoader,  # 用于 Markdown
    UnstructuredWordDocumentLoader  # 用于 DOCX
)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import List, Any, Dict, Union

logger = logging.getLogger(__name__)


async def load_and_split_file(
        file_path: str,
        file_type: str,  # 'xlsx', 'csv', 'pdf', 'txt', 'md', 'docx'
) -> List[Document]:
    """
    异步加载多种类型的文件，分割成块，并添加基础元数据。
    """
    logger.info(f"加载文件: {file_path} (类型: {file_type})")
    loader: Union[
        UnstructuredExcelLoader, CSVLoader, PyPDFLoader, TextLoader,
        UnstructuredMarkdownLoader, UnstructuredWordDocumentLoader
    ]  # 更新类型提示

    if file_type == 'xlsx':
        loader = UnstructuredExcelLoader(file_path, mode="elements")
    elif file_type == 'csv':
        try:
            loader = CSVLoader(file_path=file_path, encoding='utf-8')
        except Exception:
            loader = CSVLoader(file_path=file_path)
    elif file_type == 'pdf':
        # 对于 PDF，UnstructuredPDFLoader 通常更强大，但 PyPDFLoader 更简单
        # 您可以根据需要选择 UnstructuredPDFLoader(file_path, mode="elements")
        loader = PyPDFLoader(file_path)
    elif file_type == 'txt':
        # 尝试 UTF-8，如果失败，可以考虑其他编码或让 TextLoader 自动检测
        try:
            loader = TextLoader(file_path, encoding='utf-8')
        except Exception:
            loader = TextLoader(file_path)  # 回退到 TextLoader 的默认行为
    elif file_type == 'md':  # Markdown
        loader = UnstructuredMarkdownLoader(file_path, mode="elements")
    elif file_type == 'docx':  # Word 文档
        loader = UnstructuredWordDocumentLoader(file_path, mode="elements")
    else:
        logger.error(f"不支持的文件类型进行 RAG 处理: {file_type}")
        raise ValueError(f"不支持的文件类型进行 RAG 处理: {file_type}")

    documents: List[Document] = []
    try:
        logger.debug(f"执行 loader.aload() for {file_path}")
        documents = await loader.aload()  # 大部分加载器支持 aload
        logger.info(f"从 {file_path} 加载了 {len(documents)} 个初始文档。")
    except Exception as e:
        logger.error(f"使用主加载器加载文件 {file_path} 时出错: {e}", exc_info=True)
        # 特定 CSV 回退逻辑 (可以保留或根据新加载器调整)
        if file_type == 'csv' and 'utf-8' in str(e).lower():
            common_encodings = ['gbk', 'latin-1', 'iso-8859-1']
            for enc in common_encodings:
                logger.warning(f"尝试使用编码 {enc} 重新加载 CSV {file_path}...")
                try:
                    loader = CSVLoader(file_path=file_path, encoding=enc)
                    documents = await loader.aload()
                    logger.info(f"使用 {enc} 编码成功加载了 {len(documents)} 个文档。")
                    break
                except Exception as e2:
                    logger.error(f"使用编码 {enc} 加载 CSV 文件 {file_path} 失败: {e2}")
            if not documents:
                logger.error(f"尝试多种编码后仍无法加载 CSV 文件 {file_path}。")
                return []
        else:
            return []  # 其他加载失败返回空列表

    if not documents:
        logger.warning(f"未能从文件加载任何文档: {file_path}")
        return []

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False,
    )

    try:
        logger.debug(f"正在分割 {len(documents)} 个文档...")
        # 有些加载器（如 PyPDFLoader）直接返回 Document 列表，这些列表本身就是“块”（每页一个文档）
        # RecursiveCharacterTextSplitter 仍然可以处理它们，进一步分割长页面。
        split_docs = await asyncio.to_thread(text_splitter.split_documents, documents)
        logger.info(f"分割成 {len(split_docs)} 个块。")
    except Exception as split_error:
        logger.error(f"分割来自 {file_path} 的文档时出错: {split_error}", exc_info=True)
        return []

    filename = os.path.basename(file_path)
    final_docs: List[Document] = []
    for i, doc in enumerate(split_docs):
        metadata: Dict[str, Any] = doc.metadata.copy() if doc.metadata else {}
        metadata["source"] = filename
        metadata["chunk_index"] = i
        serializable_metadata = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool, list, dict)):
                serializable_metadata[k] = v
            elif v is not None:
                serializable_metadata[k] = str(v)
        try:
            metadata['raw_metadata'] = json.dumps(serializable_metadata, ensure_ascii=False, default=str)
        except TypeError as json_error:
            logger.warning(f"无法序列化文件 {filename} 块 {i} 的元数据: {json_error}。元数据: {serializable_metadata}")
            metadata['raw_metadata'] = json.dumps({"error": "无法序列化的元数据"})
        page_content_str = str(doc.page_content) if doc.page_content is not None else ""
        final_docs.append(Document(page_content=page_content_str, metadata=metadata))

    logger.info(f"为 {filename} 准备了 {len(final_docs)} 个最终 Document 对象。")
    return final_docs
