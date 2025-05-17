# api/dependencies.py
from typing_extensions import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from database.database import async_session_maker

# 获取主数据库会话的依赖
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session: AsyncSession = async_session_maker()
    print(f"依赖: 获取数据库会话 {id(session)}") # 调试日志
    try:
        yield session
        await session.commit()
        print(f"依赖: 提交数据库会话 {id(session)}") # 调试日志
    except Exception as e:
        print(f"依赖: 回滚数据库会话 {id(session)} due to {e}") # 调试日志
        await session.rollback()
        raise # 重新抛出异常，让 FastAPI 处理
    finally:
        await session.close()
        print(f"依赖: 关闭数据库会话 {id(session)}") # 调试日志