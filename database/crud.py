# database/crud.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, delete, and_, update, or_
from typing import List, Optional
import uuid
from . import models
from api import schemas
from agent.rag.vector_store import delete_chunks_from_vector_store
import asyncio


# --- User CRUD (保持不变) ---
async def get_user(db: AsyncSession, user_id: int) -> Optional[models.User]:
    result = await db.execute(select(models.User).filter(models.User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[models.User]:
    result = await db.execute(select(models.User).filter(models.User.username == username))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, user: schemas.UserCreateInternal) -> models.User:
    db_user = models.User(username=user.username, hashed_password=user.hashed_password)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


# --- Session CRUD ---
async def create_session(db: AsyncSession, user_id: int) -> models.Session:
    db_session = models.Session(user_id=user_id)
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)
    return db_session


async def get_session(db: AsyncSession, session_id: str) -> Optional[models.Session]:
    result = await db.execute(select(models.Session).filter(models.Session.id == session_id))
    return result.scalar_one_or_none()


async def get_sessions_by_user(db: AsyncSession, user_id: int, skip: int = 0, limit: int = 100) -> List[models.Session]:
    result = await db.execute(
        select(models.Session)
        .filter(models.Session.user_id == user_id)
        .order_by(models.Session.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    session_to_delete = await get_session(db, session_id)
    if not session_to_delete:
        return False

    chunk_ids_to_delete = await get_chunk_ids_by_session_id(db, session_id)
    if chunk_ids_to_delete:
        print(f"尝试从向量存储中删除 {len(chunk_ids_to_delete)} 个与会话 {session_id} 关联的块")
        try:
            deleted_vector_count = await asyncio.to_thread(delete_chunks_from_vector_store, chunk_ids_to_delete)
            print(f"从向量存储中删除了 {deleted_vector_count} 个与会话 {session_id} 关联的块")
        except Exception as vector_delete_error:
            print(f"从向量存储删除会话 {session_id} 的块时出错: {vector_delete_error}")

    print(f"从数据库删除会话 {session_id} (CASCADE 将处理关联的消息, DocumentChunks, 和 StoredFiles)...")
    stmt = delete(models.Session).where(models.Session.id == session_id)
    result = await db.execute(stmt)
    # 提交由依赖作用域处理 (通常在 api.dependencies.get_db_session 中)
    if result.rowcount > 0:
        print(f"会话 {session_id} 在数据库中标记为待删除。")
        return True
    else:
        print(f"警告: 最初找到了会话 {session_id}，但数据库删除语句影响了 0 行。")
        return False


# --- Message CRUD (保持不变) ---
async def add_message(db: AsyncSession, message: schemas.MessageCreateDB) -> models.Message:
    db_message = models.Message(**message.model_dump())
    db.add(db_message)
    await db.flush()
    await db.refresh(db_message)
    return db_message


async def get_messages_by_session(db: AsyncSession, session_id: str, skip: int = 0, limit: int = 100) -> List[
    models.Message]:
    result = await db.execute(
        select(models.Message)
        .filter(models.Message.session_id == session_id)
        .order_by(models.Message.timestamp.asc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


# --- KnowledgeUpload CRUD ---
async def create_knowledge_upload(db: AsyncSession, upload: schemas.KnowledgeUploadCreate) -> models.KnowledgeUpload:
    """创建新的知识库上传记录，并关联到 StoredFile"""
    db_upload = models.KnowledgeUpload(
        original_filename=upload.original_filename,
        uploader_id=upload.uploader_id,
        status="processing",
        stored_file_id=upload.stored_file_id  # 保存 StoredFile 的 ID
    )
    db.add(db_upload)
    await db.commit()  # 立即提交以确保获得 ID 和默认值
    await db.refresh(db_upload)
    return db_upload


async def get_knowledge_upload(db: AsyncSession, upload_id: str) -> Optional[models.KnowledgeUpload]:
    result = await db.execute(select(models.KnowledgeUpload).filter(models.KnowledgeUpload.id == upload_id))
    return result.scalar_one_or_none()


async def list_knowledge_uploads(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[models.KnowledgeUpload]:
    result = await db.execute(
        select(models.KnowledgeUpload)
        .order_by(models.KnowledgeUpload.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def update_knowledge_upload_status(db: AsyncSession, upload_id: str, status: str) -> bool:
    stmt = (
        update(models.KnowledgeUpload)
        .where(models.KnowledgeUpload.id == upload_id)
        .values(status=status)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def delete_knowledge_upload(db: AsyncSession, upload_id: str) -> tuple[bool, Optional[str]]:
    """
    删除 KnowledgeUpload 记录。
    - 数据库 CASCADE 会处理关联的 DocumentChunk (DB中的)。
    - 调用此函数前，应已处理向量存储中的块删除。
    - 此函数现在也会尝试删除关联的 StoredFile 原始文件。
    返回一个元组 (deletion_success: bool, deleted_stored_file_id: Optional[str])
    """
    upload_record = await get_knowledge_upload(db, upload_id)
    if not upload_record:
        return False, None

    deleted_sf_id: Optional[str] = None
    # 如果 KnowledgeUpload 表中有关联的 stored_file_id，则删除 StoredFile
    if upload_record.stored_file_id:
        sf_deleted = await delete_stored_file(db, upload_record.stored_file_id)
        if sf_deleted:
            print(f"原始文件 StoredFile ID {upload_record.stored_file_id} 已从数据库删除。")
            deleted_sf_id = upload_record.stored_file_id
        else:
            print(f"警告: 未能从数据库删除原始文件 StoredFile ID {upload_record.stored_file_id}。")

    stmt = delete(models.KnowledgeUpload).where(models.KnowledgeUpload.id == upload_id)
    result = await db.execute(stmt)
    # 提交由依赖作用域处理
    return result.rowcount > 0, deleted_sf_id


# --- DocumentChunk CRUD (保持不变) ---
# ... (保持不变) ...
async def add_document_chunks(db: AsyncSession, chunks: List[schemas.DocumentChunkCreate],
                              user_id: Optional[int] = None) -> List[models.DocumentChunk]:
    if not chunks:
        return []
    db_chunks = []
    for chunk_schema in chunks:
        if not chunk_schema.upload_id and not chunk_schema.session_id:
            raise ValueError(
                f"DocumentChunkCreate 必须有关联的 upload_id 或 session_id。源: {chunk_schema.document_source} 两者皆无")
        if chunk_schema.upload_id and chunk_schema.session_id:  # DocumentChunk 要么关联 upload_id (知识库), 要么关联 session_id (会话上下文), 不能同时关联
            raise ValueError(
                f"DocumentChunkCreate 只能关联 upload_id 或 session_id 之一。源: {chunk_schema.document_source} 两者皆有")
        chunk_data = chunk_schema.model_dump()
        if user_id:
            chunk_data['user_id'] = user_id
        db_chunks.append(models.DocumentChunk(**chunk_data))
    db.add_all(db_chunks)
    await db.flush()
    return db_chunks


async def get_chunk_ids_by_session_id(db: AsyncSession, session_id: str) -> List[str]:
    stmt = select(models.DocumentChunk.id).where(models.DocumentChunk.session_id == session_id)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_chunk_ids_by_upload_id(db: AsyncSession, upload_id: str) -> List[str]:
    stmt = select(models.DocumentChunk.id).where(models.DocumentChunk.upload_id == upload_id)
    result = await db.execute(stmt)
    return result.scalars().all()


async def delete_document_chunks_by_ids(db: AsyncSession, chunk_ids: List[str]) -> int:
    if not chunk_ids:
        return 0
    stmt = delete(models.DocumentChunk).where(models.DocumentChunk.id.in_(chunk_ids))
    result = await db.execute(stmt)
    return result.rowcount


async def get_document_chunk(db: AsyncSession, chunk_id: str) -> Optional[models.DocumentChunk]:
    result = await db.execute(select(models.DocumentChunk).filter(models.DocumentChunk.id == chunk_id))
    return result.scalar_one_or_none()


# --- StoredFile CRUD ---
async def create_stored_file(db: AsyncSession, file_metadata: schemas.StoredFileCreate,
                             file_bytes: bytes) -> models.StoredFile:
    """将新文件的元数据和内容存储到数据库。"""
    generated_id = str(uuid.uuid4())
    db_file = models.StoredFile(
        id=generated_id,
        original_filename=file_metadata.original_filename,
        file_type=file_metadata.file_type,
        file_content=file_bytes,
        content_length=len(file_bytes),
        uploader_id=file_metadata.uploader_id,
        session_id=file_metadata.session_id  # 如果是会话文件，则保存 session_id
    )
    db.add(db_file)
    # 如果在同一个事务中还需要用这个 StoredFile 的 ID, 例如关联到 KnowledgeUpload,
    # 那么 flush 是必要的。如果不需要立即使用 ID，则可以依赖 get_db_session 中的 commit。
    await db.flush()  # 确保在 KnowledgeUpload 创建前，StoredFile 的 ID 可用
    await db.refresh(db_file)
    return db_file


async def get_stored_file(db: AsyncSession, file_id: str) -> Optional[models.StoredFile]:
    """通过其 ID 检索存储的文件。"""
    result = await db.execute(select(models.StoredFile).filter(models.StoredFile.id == file_id))
    return result.scalar_one_or_none()


async def delete_stored_file(db: AsyncSession, file_id: str) -> bool:
    """从数据库中删除存储的文件记录。"""
    stmt = delete(models.StoredFile).where(models.StoredFile.id == file_id)
    result = await db.execute(stmt)
    # 提交通常由 get_db_session 处理，除非这里需要立即生效且独立于请求的其余部分
    # await db.commit()
    return result.rowcount > 0
