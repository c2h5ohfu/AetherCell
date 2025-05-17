# api/routers/files.py
import os
import uuid
import aiofiles
import asyncio
import logging
from fastapi import (
    APIRouter, Depends, HTTPException, status, UploadFile, File,
    Form, BackgroundTasks, Body, Path
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import Annotated, List, Optional, Any

from api import schemas, security
from api.dependencies import get_db_session
from database import crud, models
from database.models import generate_uuid_str
from database.database import async_session_maker

from agent.rag.file_processing import load_and_split_file
from agent.rag.vector_store import add_chunks_to_vector_store, delete_chunks_from_vector_store
from agent.agent_runner import run_supervisor, get_last_ai_message_content
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

UPLOAD_DIR = "uploads_temp"  # 临时文件目录，用于RAG处理前的文件暂存
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(
    prefix="/files",
    tags=["Files"],
    dependencies=[Depends(security.get_current_active_user)],
)

DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ActiveUserDep = Annotated[models.User, Depends(security.get_current_active_user)]
SessionIDPathDep = Annotated[str, Path(..., description="文件要关联的聊天会话 ID")]
KnowledgeFileDep = Annotated[
    UploadFile, File(..., description="用于公共知识库的文件 (.xlsx, .csv, .pdf, .txt, .md, .docx)")]
SessionFileDep = Annotated[
    UploadFile, File(..., description="用于当前会话上下文的文件 (.xlsx, .csv, .pdf, .txt, .md, .docx)")]


async def process_knowledge_file_background(
        temp_filepath: str,
        file_type: str,  # 文件扩展名, e.g., "pdf"
        knowledge_upload_id: str,  # KnowledgeUpload 表的 ID
        original_filename: str,
        uploader_id: int,
        db_session_maker_func,
):
    """后台任务: 处理上传到公共知识库的文件，进行 embedding 并存入向量库。"""
    logger.info(
        f"[知识库后台] 开始处理: {original_filename} (KnowledgeUploadID: {knowledge_upload_id}, FileType: {file_type})")
    processing_success = False

    try:
        langchain_documents = await load_and_split_file(temp_filepath, file_type)
        if not langchain_documents:
            logger.warning(f"[知识库后台] 未为 {original_filename} 生成任何块。")
            async with db_session_maker_func() as session:
                await crud.update_knowledge_upload_status(session, knowledge_upload_id, "failed: no chunks")
                await session.commit()
            return

        chunks_to_db: List[schemas.DocumentChunkCreate] = []
        chunk_ids_generated = [generate_uuid_str() for _ in langchain_documents]

        for i, doc in enumerate(langchain_documents):
            chunk_id = chunk_ids_generated[i]
            doc.metadata['db_chunk_id'] = chunk_id
            chunks_to_db.append(schemas.DocumentChunkCreate(
                id=chunk_id,
                upload_id=knowledge_upload_id,  # 关联到 KnowledgeUpload 记录
                session_id=None,  # 知识库文件不关联特定会话
                document_source=original_filename,
                chunk_index=i,
                content=doc.page_content,
                metadata_json=doc.metadata.get('raw_metadata', '{}'),
            ))

        # 对于知识库文件，session_id 传 None 给向量存储，表示这是全局知识
        await add_chunks_to_vector_store(langchain_documents, chunk_ids_generated, session_id=None)
        logger.info(f"[知识库后台] {len(langchain_documents)} 个块已添加到向量存储 (全局知识)。")

        async with db_session_maker_func() as session:
            try:
                await crud.add_document_chunks(session, chunks_to_db, user_id=uploader_id)
                await crud.update_knowledge_upload_status(session, knowledge_upload_id, "completed")
                await session.commit()
                processing_success = True
                logger.info(f"[知识库后台] {original_filename} 的块元数据已保存，状态更新为 completed。")
            except Exception as db_error:
                await session.rollback()
                logger.error(f"[知识库后台] 保存块元数据或更新状态时出错 ({original_filename}): {db_error}",
                             exc_info=True)
                # 再次尝试更新状态为失败
                try:
                    await crud.update_knowledge_upload_status(session, knowledge_upload_id, f"failed: db error")
                    await session.commit()
                except Exception as status_update_err:
                    logger.error(f"[知识库后台] 再次更新失败状态时出错: {status_update_err}")
                    await session.rollback()  # 回滚第二次尝试
    except Exception as e:
        logger.error(f"[知识库后台] 处理 {original_filename} 时发生总体错误: {e}", exc_info=True)
        if not processing_success:  # 仅当之前未成功时更新
            async with db_session_maker_func() as session:
                try:
                    # 检查状态，避免覆盖已经明确设置的失败状态
                    current_upload_status = await crud.get_knowledge_upload(session, knowledge_upload_id)
                    if current_upload_status and current_upload_status.status == "processing":
                        await crud.update_knowledge_upload_status(session, knowledge_upload_id,
                                                                  f"failed: processing error")
                        await session.commit()
                except Exception as final_status_update_err:
                    logger.error(f"[知识库后台] 更新最终失败状态时出错: {final_status_update_err}")
                    await session.rollback()
    finally:
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError as remove_err:
                logger.error(f"[知识库后台] 清理临时文件 {temp_filepath} 时出错: {remove_err}")


@router.post(
    "/upload/knowledge",
    response_model=schemas.KnowledgeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传文件到公共知识库 (文件存入DB, 异步Embedding)"
)
async def upload_knowledge_file_handler(
        background_tasks: BackgroundTasks,
        current_user: ActiveUserDep,
        db: DBSessionDep,
        file: KnowledgeFileDep,
):
    allowed_extensions = {".xlsx", ".csv", ".pdf", ".txt", ".md", ".docx"}
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"无效的文件类型。仅支持 {', '.join(allowed_extensions)}。")
    file_type_for_rag_processing = file_extension[1:]  # e.g., "pdf"

    # 1. 将原始文件保存到 StoredFile 表
    stored_file_db_entry: Optional[models.StoredFile] = None
    try:
        file_content_bytes = await file.read()
        await file.seek(0)  # 重置文件指针，以便后续读取到临时文件

        stored_file_schema = schemas.StoredFileCreate(
            original_filename=file.filename,
            file_type=file.content_type if file.content_type else file_type_for_rag_processing,
            uploader_id=current_user.id,
            session_id=None  # 知识库文件不关联特定会话，所以 session_id 为 None
        )
        stored_file_db_entry = await crud.create_stored_file(db, file_metadata=stored_file_schema,
                                                             file_bytes=file_content_bytes)
        logger.info(f"API: 原始知识库文件 '{file.filename}' 已保存到 StoredFiles 表，ID: {stored_file_db_entry.id}")
    except Exception as e_stored_file:
        logger.error(f"API: 保存原始知识库文件 '{file.filename}' 到数据库失败: {e_stored_file}", exc_info=True)
        raise HTTPException(status_code=500, detail="无法将原始文件保存到数据库。")

    # 2. 创建 KnowledgeUpload 记录，并关联 StoredFile
    knowledge_upload_entry: Optional[models.KnowledgeUpload] = None
    try:
        upload_create_data = schemas.KnowledgeUploadCreate(
            original_filename=file.filename,
            uploader_id=current_user.id,
            stored_file_id=stored_file_db_entry.id  # 关联到已存储的原始文件
        )
        knowledge_upload_entry = await crud.create_knowledge_upload(db, upload=upload_create_data)
        logger.info(
            f"API: 已创建知识库上传记录 {knowledge_upload_entry.id} (文件: '{file.filename}') 并关联 StoredFile ID: {stored_file_db_entry.id}")
    except Exception as create_err:
        logger.error(f"API: 创建知识库上传记录失败: {create_err}", exc_info=True)
        # 注意：如果此处失败，已创建的 StoredFile 记录可能会成为孤立记录，需要考虑清理机制或事务处理。
        # 为了简单起见，暂时不处理 StoredFile 的回滚，但生产环境应考虑。
        raise HTTPException(status_code=500, detail="创建知识库上传记录失败。")

    # 3. 保存临时文件以供后台 RAG 处理
    temp_filename = f"{uuid.uuid4()}{file_extension}"
    temp_filepath = os.path.join(UPLOAD_DIR, temp_filename)
    try:
        async with aiofiles.open(temp_filepath, 'wb') as out_file:
            while content_chunk := await file.read(1024 * 1024):  # 1MB chunks
                await out_file.write(content_chunk)
    except Exception as save_err:
        logger.error(f"API: 保存临时文件 {temp_filepath} 失败: {save_err}", exc_info=True)
        await crud.update_knowledge_upload_status(db, knowledge_upload_entry.id, "failed: save temp file error")
        # await db.commit() # 确保状态更新被提交
        raise HTTPException(status_code=500, detail="保存上传的文件以供RAG处理失败。")
    finally:
        await file.close()

    # 4. 添加后台 RAG 处理任务
    background_tasks.add_task(
        process_knowledge_file_background,
        temp_filepath=temp_filepath,
        file_type=file_type_for_rag_processing,
        knowledge_upload_id=knowledge_upload_entry.id,
        original_filename=file.filename,
        uploader_id=current_user.id,
        db_session_maker_func=async_session_maker
    )

    return schemas.KnowledgeUploadResponse(
        filename=file.filename,
        message="文件已接收并存入数据库，正在后台进行 Embedding 处理以添加到知识库。",
        upload_id=knowledge_upload_entry.id,
        stored_file_id=stored_file_db_entry.id
    )


@router.post(
    "/upload/session/{session_id}",
    response_model=schemas.SessionFileUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="上传文件作为当前会话上下文 (文件存入DB, 同步Embedding)"
)
async def upload_session_file_handler(
        session_id: SessionIDPathDep,
        current_user: ActiveUserDep,
        db: DBSessionDep,
        file: SessionFileDep,
):
    logger.info(f"API: 收到会话文件上传请求 (会话: {session_id}, 用户: {current_user.id}, 文件: {file.filename})")
    allowed_extensions = {".xlsx", ".csv", ".pdf", ".txt", ".md", ".docx"}
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"无效的文件类型。仅支持 {', '.join(allowed_extensions)}。")
    file_type_for_rag_processing = file_extension[1:]

    session_db_obj = await crud.get_session(db, session_id=session_id)
    if not session_db_obj:
        raise HTTPException(status_code=404, detail="会话未找到。")
    if session_db_obj.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="用户无权访问此会话。")

    stored_file_db_entry_session: Optional[models.StoredFile] = None
    temp_filename = f"{uuid.uuid4()}{file_extension}"  # 临时文件名，用于RAG处理
    temp_filepath = os.path.join(UPLOAD_DIR, temp_filename)
    langchain_documents: List[Any] = []

    try:
        # 1. 将原始会话文件保存到 StoredFile 表，并关联 session_id
        file_content_bytes_for_db = await file.read()
        await file.seek(0)  # 重置文件指针

        stored_file_schema_session = schemas.StoredFileCreate(
            original_filename=file.filename,
            file_type=file.content_type if file.content_type else file_type_for_rag_processing,
            uploader_id=current_user.id,
            session_id=session_id  # 关键：关联到当前会话
        )
        stored_file_db_entry_session = await crud.create_stored_file(db, file_metadata=stored_file_schema_session,
                                                                     file_bytes=file_content_bytes_for_db)
        logger.info(
            f"API: 原始会话文件 '{file.filename}' 已保存到 StoredFiles 表 (ID: {stored_file_db_entry_session.id}) 并关联到会话 {session_id}")

        # 2. 保存临时文件以供 RAG 处理 (用于提取文本块)
        try:
            async with aiofiles.open(temp_filepath, 'wb') as out_file:
                while content_chunk := await file.read(1024 * 1024):
                    await out_file.write(content_chunk)
        except Exception as save_err:
            logger.error(f"API: 保存临时会话文件 {temp_filepath} 失败: {save_err}", exc_info=True)
            raise HTTPException(status_code=500, detail="保存上传的会话文件以供RAG处理失败。")
        finally:
            await file.close()  # 关闭 FastAPI 的 UploadFile 对象

        # 3. 同步 RAG 处理步骤 (加载、分割、存入向量库并打上 session_id 标签)
        langchain_documents = await load_and_split_file(temp_filepath, file_type_for_rag_processing)
        if not langchain_documents:
            logger.warning(f"API: 未为会话文件 {file.filename} 生成任何 RAG 块。")
            # 即使没有块，原始文件也已存入 StoredFile，但这里可能需要一个更明确的错误或处理
            # raise HTTPException(status_code=422, detail="文件无法处理或未生成内容块以供RAG使用。")
            # 或者，返回一个不同的消息给用户
            return schemas.SessionFileUploadResponse(
                filename=file.filename,
                message=f"文件 '{file.filename}' 已保存，但未能从中提取有效内容以供当前会话上下文使用。",
                upload_type="session",
                assistant_acknowledgment="请注意，我已收到文件，但似乎无法从中提取文本内容。",
                chunk_count=0,
                stored_file_id=stored_file_db_entry_session.id if stored_file_db_entry_session else None
            )

        chunks_to_db_session: List[schemas.DocumentChunkCreate] = []
        chunk_ids_generated_session = [generate_uuid_str() for _ in langchain_documents]

        for i, doc in enumerate(langchain_documents):
            chunk_id = chunk_ids_generated_session[i]
            doc.metadata['db_chunk_id'] = chunk_id
            chunks_to_db_session.append(schemas.DocumentChunkCreate(
                id=chunk_id,
                upload_id=None,  # 会话文件不关联 KnowledgeUpload
                session_id=session_id,  # 关联到当前会话
                document_source=file.filename,  # 原始文件名
                chunk_index=i,
                content=doc.page_content,
                metadata_json=doc.metadata.get('raw_metadata', '{}'),
            ))

        # 添加到向量存储时，传入 session_id 以便后续过滤
        await add_chunks_to_vector_store(langchain_documents, chunk_ids_generated_session, session_id=session_id)
        logger.info(f"API: 会话块已添加到向量存储 for RAG (会话: {session_id})。")

        await crud.add_document_chunks(db, chunks_to_db_session, user_id=current_user.id)
        logger.info(f"API: 会话块元数据已添加到数据库 for RAG (会话: {session_id})。")

        # 4. AI 确认 (保持不变)
        assistant_ack_content: Optional[str] = None
        preview_text = langchain_documents[0].page_content[:500] if langchain_documents else "[无内容预览]"
        agent_input_content = (
            f"用户 '{current_user.username}' 刚刚上传了名为 '{file.filename}' 的文件到我们当前的会话 ({session_id})。"
            f"我已经将其处理成 {len(langchain_documents)} 个块并添加到了我们会话的上下文中。"
            f"请提供一个简短的确认，表明你收到了这个文件上下文。"
            f"这是一个简短的预览:\n```\n{preview_text}...\n```"
        )
        agent_input_message = HumanMessage(content=agent_input_content)
        user_info_for_agent = {"user_id": current_user.id, "username": current_user.username, "session_id": session_id}
        final_agent_state = await run_supervisor(session_id, agent_input_message, user_info_for_agent)
        assistant_ack_content = get_last_ai_message_content(final_agent_state)
        if final_agent_state.get("error"):
            logger.error(f"API: Agent 在确认期间返回错误: {final_agent_state.get('error')}")
            assistant_ack_content = "[Agent 未能生成确认信息]"
        elif not assistant_ack_content:
            logger.warning("API: Agent 未提供确认消息。")
            assistant_ack_content = "[Agent 未提供确认]"
        else:
            logger.info(f"API: 收到会话文件的 AI 确认。")
            ack_message_db = schemas.MessageCreateDB(
                session_id=session_id, user_id=None, role="assistant", content=assistant_ack_content
            )
            await crud.add_message(db, ack_message_db)
            logger.info("API: AI 确认消息已保存到聊天记录。")

        # 5. 返回成功响应
        return schemas.SessionFileUploadResponse(
            filename=file.filename,
            message=f"文件已处理并添加到会话 {session_id} 上下文。",
            assistant_acknowledgment=assistant_ack_content,
            chunk_count=len(langchain_documents),
            stored_file_id=stored_file_db_entry_session.id if stored_file_db_entry_session else None
        )

    except HTTPException as http_exc:
        # 如果 StoredFile 创建失败但我们决定不立即抛出，这里可能不会被触发。
        # 确保所有预期的 HTTPException 都被正确处理。
        raise http_exc
    except Exception as e:
        logger.error(f"API: 处理会话文件上传时发生未处理错误 (会话: {session_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理会话文件时发生内部服务器错误: {e}")
    finally:
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError as remove_err:
                logger.error(f"API: 清理临时会话文件 {temp_filepath} 时出错: {remove_err}")


@router.get(
    "/knowledge",
    response_model=schemas.ListKnowledgeUploadsResponse,
    status_code=status.HTTP_200_OK,
    summary="列出所有公共知识库上传记录",
)
async def list_knowledge_uploads_handler(
        db: DBSessionDep,
        skip: int = 0,
        limit: int = 100,
):
    uploads = await crud.list_knowledge_uploads(db, skip=skip, limit=limit)
    validated_uploads = [schemas.KnowledgeUploadRead.model_validate(up) for up in uploads]
    return schemas.ListKnowledgeUploadsResponse(uploads=validated_uploads)


@router.delete(
    "/knowledge/{upload_id}",  # upload_id 是 KnowledgeUpload 表的 ID
    response_model=schemas.DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="删除知识库上传、其向量及关联的原始文件",
)
async def delete_knowledge_upload_handler(
        upload_id: Annotated[str, Path(..., description="要删除的知识库上传记录的 ID (UUID)")],
        current_user: ActiveUserDep,
        db: DBSessionDep,
):
    logger.info(f"API: 收到删除知识库上传 {upload_id} 的请求 (用户: {current_user.id})。")
    upload_record = await crud.get_knowledge_upload(db, upload_id=upload_id)  # 获取 KnowledgeUpload 记录
    if not upload_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到知识库上传记录 {upload_id}。")

    # 1. 从向量存储删除关联的块
    chunk_ids = await crud.get_chunk_ids_by_upload_id(db, upload_id=upload_id)
    deleted_vector_count = 0
    if chunk_ids:
        logger.info(f"API: 尝试从向量存储删除 {len(chunk_ids)} 个与知识库上传 {upload_id} 关联的块...")
        try:
            deleted_vector_count = await asyncio.to_thread(delete_chunks_from_vector_store, chunk_ids)
            logger.info(f"API: 向量存储删除完成 ({deleted_vector_count} 个块)。")
        except Exception as vector_del_err:
            logger.error(f"API: 删除知识库上传 {upload_id} 的向量块时出错: {vector_del_err}", exc_info=True)

    # 2. 从数据库删除 KnowledgeUpload 记录 (这将级联删除 DocumentChunk)
    #    crud.delete_knowledge_upload 现在也会尝试删除关联的 StoredFile
    logger.info(f"API: 正在从数据库删除知识库上传记录 {upload_id} 及其关联数据...")
    try:
        # crud.delete_knowledge_upload 返回 (bool, Optional[str])
        # bool 表示 KnowledgeUpload 是否成功删除, str 是已删除的 StoredFile ID (如果有关联且成功删除)
        ku_deleted, deleted_sf_id = await crud.delete_knowledge_upload(db, upload_id)
        if not ku_deleted:
            # 这不应该发生，因为上面已经 get_knowledge_upload 了
            raise HTTPException(status_code=404, detail="知识库上传记录找到但从数据库删除失败。")
        logger.info(f"API: 知识库上传记录 {upload_id} 已在数据库中标记为待删除。")
        if deleted_sf_id:
            logger.info(f"API: 关联的原始文件 StoredFile ID {deleted_sf_id} 也已删除。")

    except Exception as db_del_err:
        logger.error(f"API: 从数据库删除知识库上传记录 {upload_id} 或其关联 StoredFile 时出错: {db_del_err}",
                     exc_info=True)
        raise HTTPException(status_code=500, detail="从数据库删除知识库上传记录或其关联原始文件失败。")

    # 提交将由 get_db_session 依赖处理

    message = (
        f"成功启动知识库上传 {upload_id} 的删除。"
        f"数据库记录已删除。尝试删除的向量块数量: {deleted_vector_count}。"
    )
    if deleted_sf_id:
        message += f" 关联的原始文件 (ID: {deleted_sf_id}) 也已删除。"
    if chunk_ids and deleted_vector_count < len(chunk_ids):
        message += " (注意: 向量删除可能遇到错误或部分成功，请检查日志。)"
    return schemas.DeleteResponse(success=True, message=message)


