# database/database.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

load_dotenv()

# --- 使用 SQLite 连接字符串 ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./sql_app.db")
# --- 结束 ---

engine = create_async_engine(DATABASE_URL, echo=False)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()

async def init_db():
    """初始化数据库,创建所有表 (包括新的 KnowledgeUpload)"""
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all) # 开发时可能取消注释以清空
        await conn.run_sync(Base.metadata.create_all)

async def dispose_engine():
    """关闭数据库引擎连接"""
    await engine.dispose()
    print("Database engine disposed (SQLite).")