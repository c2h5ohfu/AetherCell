# agent/rag/vector_store.py
import os
import chromadb
from chromadb.config import Settings
from langchain_core.documents import Document
from dotenv import load_dotenv
from typing import List, Dict, Tuple, Optional, Any
from langchain_ollama import OllamaEmbeddings
from typing_extensions import Union  # 保留 Union
import logging  # 使用日志记录

load_dotenv()
logger = logging.getLogger(__name__)

# --- 配置 ---
CHROMA_PERSIST_DIRECTORY = os.getenv("CHROMA_PERSIST_DIRECTORY", "./chroma_db_combined")  # 如果结构改变，考虑重命名目录
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")  # Ollama 服务地址
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "nomic-embed-text")  # 嵌入模型名称
# 使用单一集合存储公共知识和会话特定数据
# 通过元数据过滤来区分它们
COLLECTION_NAME = "knowledge_and_session_store"

# --- 初始化 ---
embedding_function_kwargs = {}
if OLLAMA_BASE_URL:
    embedding_function_kwargs["base_url"] = OLLAMA_BASE_URL

try:
    embedding_function = OllamaEmbeddings(
        model=EMBEDDING_MODEL_NAME,
        **embedding_function_kwargs
    )
    # 简单的测试查询
    test_emb = embedding_function.embed_query("test")
    logger.info(f"初始化并测试 OllamaEmbeddings 模型: {EMBEDDING_MODEL_NAME}")
except Exception as e:
    logger.error(f"初始化或测试 OllamaEmbeddings 时出错: {e}", exc_info=True)
    logger.error(f"请确保 Ollama 服务正在运行并且模型 '{EMBEDDING_MODEL_NAME}' 可用。")
    raise

try:
    chroma_client = chromadb.PersistentClient(
        path=CHROMA_PERSIST_DIRECTORY,
        settings=Settings(anonymized_telemetry=False)  # 可选：禁用匿名遥测
    )
    logger.info(f"初始化 ChromaDB PersistentClient 于: {CHROMA_PERSIST_DIRECTORY}")
except Exception as e:
    logger.error(f"初始化 ChromaDB PersistentClient 时出错: {e}", exc_info=True)
    raise

try:
    # 获取或创建单一集合
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        # embedding_function=embedding_function, # Chroma >= 0.5 通常不在此处需要
        metadata={"hnsw:space": "cosine"}  # 对嵌入向量推荐的距离度量
    )
    logger.info(f"获取或创建 Chroma 集合: {COLLECTION_NAME}")
except Exception as e:
    logger.error(f"获取或创建 Chroma 集合时出错: {e}", exc_info=True)
    raise


# --- 核心函数 (修改后) ---

async def add_chunks_to_vector_store(
        chunks: List[Document],
        chunk_ids: List[str],
        session_id: Optional[str] = None  # 添加了 session_id 参数
):
    """
    异步地嵌入 Langchain Document 块并将它们添加到 ChromaDB 集合中。
    使用提供的 chunk_ids 作为 ChromaDB 的 ID。
    如果提供了 session_id，它将被添加到元数据中以供过滤。
    """
    if len(chunks) != len(chunk_ids):
        raise ValueError("数据块数量和 chunk_ids 数量必须相同。")
    if not chunks:
        logger.warning("没有要添加的数据块 (add_chunks_to_vector_store)。")
        return

    texts_to_embed = [chunk.page_content for chunk in chunks]
    embeddings: List[List[float]] = []
    try:
        logger.info(f"正在嵌入 {len(texts_to_embed)} 个文本块...")
        # 使用异步批量嵌入
        embeddings = await embedding_function.aembed_documents(texts_to_embed)
        logger.info(f"成功嵌入 {len(embeddings)} 个块。")
    except Exception as e:
        logger.error(f"嵌入过程中出错: {e}", exc_info=True)
        # 决定是接受部分嵌入还是停止
        return  # 如果嵌入失败则停止

    if len(embeddings) != len(chunks):
        logger.error(f"嵌入数量不匹配: {len(embeddings)} 个嵌入 vs {len(chunks)} 个块。中止添加。")
        return

    # 准备批量 upsert 操作
    batch_upsert: Dict[str, List[Any]] = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}

    for i, chunk in enumerate(chunks):
        chunk_id = chunk_ids[i]
        metadata = chunk.metadata.copy() if chunk.metadata else {}  # 确保元数据存在
        embedding = embeddings[i]  # 获取对应的嵌入向量

        # 如果提供了 session_id，添加到元数据
        if session_id:
            metadata['session_id'] = session_id
        else:
            # 确保公共/知识库上传的块没有 session_id 字段
            # 尽管 Chroma 过滤能优雅地处理缺失的键
            metadata.pop('session_id', None)

        # 添加数据库块 ID 到元数据以便交叉引用
        # 注意：之前可能使用了 'db_id'，确保一致性或选择一个标准键名
        metadata['db_chunk_id'] = chunk_id

        # 清理元数据以兼容 Chroma (str, int, float, bool)
        cleaned_metadata: Dict[str, Union[str, int, float, bool]] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                cleaned_metadata[key] = value
            elif value is None:
                continue  # 跳过 None 值
            else:
                # 将其他类型转换为字符串，记录警告
                logger.debug(f"转换元数据字段 '{key}' (类型 {type(value)}) 为字符串 (块 ID: {chunk_id})。")
                cleaned_metadata[key] = str(value)

        batch_upsert["ids"].append(chunk_id)
        batch_upsert["documents"].append(chunk.page_content)
        batch_upsert["metadatas"].append(cleaned_metadata)
        batch_upsert["embeddings"].append(embedding)

    # 执行批量 upsert
    if batch_upsert["ids"]:
        logger.info(f"正在添加/更新 {len(batch_upsert['ids'])} 个块到集合 '{COLLECTION_NAME}'...")
        try:
            # Chroma 操作通常是同步的
            collection.upsert(
                ids=batch_upsert["ids"],
                documents=batch_upsert["documents"],
                metadatas=batch_upsert["metadatas"],
                embeddings=batch_upsert["embeddings"]  # 提供嵌入向量
            )
            logger.info(f"成功添加/更新了 {len(batch_upsert['ids'])} 个块。")
        except Exception as e:
            logger.error(f"向 Chroma upsert 块时出错: {e}", exc_info=True)
            # 如果在更大的流程中失败，考虑回滚或更新状态
            raise  # 重新抛出异常以指示失败


# --- 格式化结果 (微小改动以增强清晰度) ---
def _format_chroma_results(chroma_results: Optional[Dict[str, Optional[List[Any]]]]) -> List[Tuple[Document, float]]:
    """将 ChromaDB 查询结果格式化为 (Document, score) 元组列表。"""
    # 检查结果是否有效且包含 ID
    if not chroma_results or not chroma_results.get("ids") or not chroma_results["ids"][0]:
        return []

    formatted_results = []
    # Chroma 查询结果是列表的列表 (每个查询嵌入一个列表)
    ids = chroma_results["ids"][0]
    documents = chroma_results.get("documents", [[]])[0]
    metadatas = chroma_results.get("metadatas", [[]])[0]
    distances = chroma_results.get("distances", [[]])[0]  # 使用距离作为分数

    for i, doc_id in enumerate(ids):
        content = documents[i] if documents and i < len(documents) else ""
        metadata = metadatas[i] if metadatas and i < len(metadatas) else {}
        # Chroma 余弦距离: 0=相同, 2=相反。越低越好。
        score = distances[i] if distances and i < len(distances) else float('inf')

        # 确保元数据中有 'source' 用于显示，如果缺少则提供默认值
        if 'source' not in metadata and 'document_source' in metadata:  # 检查别名
            metadata['source'] = metadata['document_source']
        elif 'source' not in metadata:
            metadata['source'] = '未知来源'  # 默认来源

        # 将分数添加到元数据，供 LLM/Agent 使用
        metadata['retrieval_score'] = score

        formatted_results.append(
            (Document(page_content=content, metadata=metadata), score)
        )

    # 按分数 (距离，升序) 排序
    formatted_results.sort(key=lambda x: x[1])

    return formatted_results


# --- 修改后的 query_vector_store ---
async def query_vector_store(
        query: str,
        k: int = 5,
        session_id: Optional[str] = None  # 添加了 session_id 用于过滤
) -> List[Document]:
    """
    异步查询向量存储。
    如果提供了 session_id，则将结果过滤为仅包含匹配该 session_id 的块。
    否则，查询所有块 (隐含查询公共知识，假设它们缺少 session_id)。
    """
    query_type = f"会话 '{session_id}'" if session_id else "公共知识"
    logger.info(f"查询向量存储 ({query_type}): '{query[:50]}...' (k={k})")

    try:
        # 1. 异步嵌入查询
        logger.debug("正在生成查询嵌入...")
        query_embedding = await embedding_function.aembed_query(query)
        logger.debug("查询嵌入已生成。")

        # 2. 准备 ChromaDB 查询的 'where' 过滤器
        where_filter: Optional[Dict[str, Any]] = None
        if session_id:
            # 严格过滤给定的会话
            where_filter = {"session_id": session_id}
            logger.debug(f"应用 where 过滤器: {where_filter}")
        else:
            # 对于公共知识，我们查询 *没有* session_id 的块。
            # Chroma 不直接支持 "is null" 或 "not exists"。
            # 解决方法：不带过滤器查询。如果会话块可能污染公共结果，
            # 需要更严格的方法 (例如，在知识上传期间添加 'scope':'public' 元数据标签)。
            # 假设会话块总是有 'session_id'，不带过滤器查询会隐含地
            # 目标公共块 + 可能无关的会话块。
            # 目前简化：公共查询不使用过滤器。依赖检索工具名称来指导用户/Agent。
            logger.debug("未提供 session_id，不带特定会话过滤器进行查询 (目标为公共知识)。")
            pass  # 基于当前设置，公共查询不需要过滤器

        # 3. 执行 ChromaDB 查询 (同步操作)
        logger.debug(f"执行 Chroma 查询 (k={k})...")
        query_result = collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=where_filter,  # 如果 session_id 存在，则应用过滤器
            include=["documents", "metadatas", "distances"]  # 包含距离用于排序/评分
        )
        logger.debug(f"Chroma 查询返回 {len(query_result.get('ids', [[]])[0])} 个结果。")

        # 4. 格式化结果
        formatted_results: List[Tuple[Document, float]] = _format_chroma_results(query_result)

        # 5. 提取 Document 对象
        final_docs = [doc for doc, score in formatted_results]

        logger.info(f"为 {query_type} 查询返回 {len(final_docs)} 个文档。")
        return final_docs

    except Exception as e:
        logger.error(f"执行 query_vector_store ({query_type}) 时出错: {e}", exc_info=True)
        return []  # 失败时返回空列表


# --- 新增: delete_chunks_from_vector_store ---
def delete_chunks_from_vector_store(chunk_ids: List[str]) -> int:
    """
    根据 ID 从 ChromaDB 集合中删除块。
    这是一个同步操作。
    返回尝试删除的项目的大约数量 (Chroma 不返回确切计数)。
    """
    if not chunk_ids:
        logger.warning("未提供用于从向量存储删除的块 ID。")
        return 0

    logger.info(f"尝试从 Chroma 集合 '{COLLECTION_NAME}' 中删除 {len(chunk_ids)} 个块...")
    try:
        # Chroma 的 delete 是同步的
        collection.delete(ids=chunk_ids)
        # 注意：Chroma 的删除操作不一定可靠地返回已删除项的计数。
        # 我们返回尝试删除的 ID 数量。
        logger.info(f"Chroma 删除操作已完成 ({len(chunk_ids)} 个 ID)。")
        return len(chunk_ids)
    except Exception as e:
        logger.error(f"从 Chroma 删除块 {chunk_ids} 时出错: {e}", exc_info=True)
        # 根据需求，你可能希望抛出异常或仅记录错误并返回 0。
        raise  # 重新抛出以在调用函数 (例如 crud.delete_session) 中指示失败
