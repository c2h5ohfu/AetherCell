# api/routers/chat.py
import asyncio
import json
import logging # 使用日志记录
from fastapi import APIRouter, Depends, HTTPException, status, Path, Body, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Dict, Any, List, Union, Optional
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage

# 绝对导入
from api import schemas, security
from api.dependencies import get_db_session
from database import crud, models
from agent.agent_runner import run_supervisor, get_last_ai_message_content
from database.database import async_session_maker # 用于后台消息保存

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
    dependencies=[Depends(security.get_current_active_user)], # 所有路由都需要认证
)

# 类型别名
DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)] # 数据库会话依赖
ActiveUserDep = Annotated[models.User, Depends(security.get_current_active_user)] # 当前活动用户依赖
SessionIDDep = Annotated[str, Path(..., description="聊天会话的 ID")] # 路径参数中的会话 ID
MessageInputDep = Annotated[schemas.MessageCreate, Body(...)] # 请求体中的消息输入

# 用于保存消息的后台任务 (不变)
async def save_message_background(message_data: schemas.MessageCreateDB):
    """后台任务，用于保存消息。"""
    # 为后台任务使用单独的会话
    async with async_session_maker() as session:
        try:
            await crud.add_message(session, message_data)
            await session.commit()
            logger.info(f"[后台任务] 已保存消息: Role={message_data.role}, Session={message_data.session_id}")
        except Exception as e:
            logger.error(f"[后台任务] 保存会话 {message_data.session_id} 的消息失败: {e}", exc_info=True)
            await session.rollback()

# 列出用户会话 (不变)
@router.get("/", response_model=schemas.ListSessionsResponse)
async def list_chat_sessions(
    current_user: ActiveUserDep,
    db: DBSessionDep,
    skip: int = 0,
    limit: int = 100
):
    """获取当前用户的所有聊天会话列表"""
    sessions = await crud.get_sessions_by_user(db, user_id=current_user.id, skip=skip, limit=limit)
    validated_sessions = [schemas.SessionRead.model_validate(s) for s in sessions]
    return schemas.ListSessionsResponse(sessions=validated_sessions)

# 创建新会话 (不变)
@router.post("/", response_model=schemas.SessionRead, status_code=status.HTTP_201_CREATED)
async def create_new_chat_session(
    current_user: ActiveUserDep,
    db: DBSessionDep
):
    """创建一个新的聊天会话"""
    session = await crud.create_session(db=db, user_id=current_user.id)
    logger.info(f"API: 为用户 {current_user.id} 创建了新会话 {session.id}")
    return schemas.SessionRead.model_validate(session)

# 发送消息 (非流式 - 更新了日志记录和 user_info 传递)
@router.post("/{session_id}", response_model=schemas.MessageRead)
async def post_message(
    session_id: SessionIDDep,
    message: MessageInputDep,
    current_user: ActiveUserDep,
    db: DBSessionDep,
):
    """向指定会话发送消息，等待 Agent 回复。"""
    logger.info(f"API: 收到来自用户 {current_user.id} 的会话 {session_id} 消息")
    # 1. 验证会话
    session = await crud.get_session(db, session_id=session_id)
    if not session: raise HTTPException(status_code=404, detail="会话未找到")
    if session.user_id != current_user.id: raise HTTPException(status_code=403, detail="无权访问此会话")

    # 2. 准备并保存用户消息 (后台)
    user_message_content = message.content.strip()
    if not user_message_content: raise HTTPException(status_code=422, detail="消息内容不能为空")
    user_message_db = schemas.MessageCreateDB(
        session_id=session_id,
        user_id=current_user.id,
        role="user",
        content=user_message_content
    )
    asyncio.create_task(save_message_background(user_message_db)) # 启动后台保存
    user_input_for_agent = HumanMessage(content=user_message_content)
    logger.debug(f"API: 会话 {session_id} 的用户消息已添加到后台保存队列。")

    # 3. 准备 Agent 输入 (用户信息，包含 session_id)
    user_info = {
        "user_id": current_user.id,
        "username": current_user.username,
        "session_id": session_id # 确保 session_id 在这里
    }

    # 4. 调用 Agent Runner
    logger.info(f"API: 正在为会话 {session_id} 调用 Agent Runner...")
    final_agent_state = await run_supervisor(session_id, user_input_for_agent, user_info)
    logger.info(f"API: Agent Runner 已完成会话 {session_id} 的处理。")

    # 5. 提取回复
    assistant_response_content = get_last_ai_message_content(final_agent_state)

    # 6. 处理 Agent 错误或无回复
    if final_agent_state.get("error"):
         error_detail = f"Agent 处理错误: {final_agent_state.get('error')}"
         logger.error(f"API: 会话 {session_id} 的 Agent 错误: {error_detail}")
         raise HTTPException(status_code=500, detail=error_detail)
    if assistant_response_content is None:
        logger.error(f"API: Agent 未能为会话 {session_id} 生成回复。")
        raise HTTPException(status_code=500, detail="Agent 未能生成回复。")

    # 7. 保存助手消息到数据库 (前台 - 在返回前等待)
    logger.info(f"API: 正在保存会话 {session_id} 的助手回复...")
    assistant_message_db = schemas.MessageCreateDB(
        session_id=session_id,
        user_id=None, # 助手消息 user_id 为 None
        role="assistant",
        content=assistant_response_content
    )
    try:
        # 使用主请求会话 'db'
        saved_assistant_message = await crud.add_message(db, assistant_message_db)
        # 提交将通过依赖管理处理
        logger.info(f"API: 会话 {session_id} 的助手消息已添加到数据库事务。")
    except Exception as db_error:
        logger.error(f"API: 保存会话 {session_id} 的助手消息失败: {db_error}", exc_info=True)
        # 回滚将通过依赖管理处理
        raise HTTPException(status_code=500, detail="保存助手回复失败。")

    # 8. 返回保存的助手消息
    return schemas.MessageRead.model_validate(saved_assistant_message)

# 获取聊天历史 (不变)
@router.get("/{session_id}/history", response_model=List[schemas.MessageRead])
async def get_chat_history(
    session_id: SessionIDDep,
    current_user: ActiveUserDep,
    db: DBSessionDep,
    skip: int = 0,
    limit: int = 100
):
    """获取指定会话的历史消息"""
    session = await crud.get_session(db, session_id=session_id)
    if not session: raise HTTPException(status_code=404, detail="会话未找到")
    if session.user_id != current_user.id: raise HTTPException(status_code=403, detail="无权访问此会话")
    messages = await crud.get_messages_by_session(db, session_id=session_id, skip=skip, limit=limit)
    return [schemas.MessageRead.model_validate(msg) for msg in messages]

# 删除会话 (验证它使用了更新后的 crud.delete_session)
@router.delete("/{session_id}", response_model=schemas.DeleteResponse)
async def delete_chat_session(
    session_id: SessionIDDep,
    current_user: ActiveUserDep,
    db: DBSessionDep
):
    """删除一个聊天会话及其关联数据（消息、会话文件/块 - DB 和向量存储）。"""
    logger.info(f"API: 收到来自用户 {current_user.id} 的删除会话 {session_id} 请求")
    # 1. 验证会话所有权 (get_session 会检查)
    session = await crud.get_session(db, session_id=session_id)
    if not session: raise HTTPException(status_code=404, detail="会话未找到")
    if session.user_id != current_user.id: raise HTTPException(status_code=403, detail="无权访问此会话")

    # 2. 调用修改后的 CRUD 删除函数
    # 这个函数现在负责查找块 ID、删除向量和删除数据库记录 (会级联删除消息/数据库块)
    try:
        deleted = await crud.delete_session(db, session_id=session_id)
        # 提交由依赖管理器处理
        if deleted:
            logger.info(f"API: 成功启动会话 {session_id} 的删除流程。")
            return schemas.DeleteResponse(success=True, message="会话及关联数据已成功删除。")
        else:
            # 这可能意味着会话在检查和调用之间已被删除
            logger.warning(f"API: crud.delete_session 对会话 {session_id} 返回 False，可能是竞争条件或先前已删除。")
            raise HTTPException(status_code=404, detail="会话未找到或已被删除。")
    except HTTPException as http_exc:
         # 重新引发来自 crud.delete_session 的 HTTP 异常 (例如向量存储失败，如果在那里未处理)
         raise http_exc
    except Exception as e:
        logger.error(f"API: 会话删除过程中发生错误 ({session_id}): {e}", exc_info=True)
        # 回滚由依赖管理器处理
        raise HTTPException(status_code=500, detail=f"删除会话失败: {e}")