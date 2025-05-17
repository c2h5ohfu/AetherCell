# database/models.py
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean, LargeBinary
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.database import Base  # 确保 Base 被正确导入
import uuid


def generate_uuid_str():
    """生成 UUID 字符串"""
    return str(uuid.uuid4())


class KnowledgeUpload(Base):
    __tablename__ = "knowledge_uploads"  # 存储知识库上传操作的元数据
    id = Column(String, primary_key=True, default=generate_uuid_str, index=True)
    original_filename = Column(String, nullable=False, index=True)  # 原始文件名
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 上传者ID
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())  # 上传时间
    status = Column(String, default="processing", nullable=False)  # 处理状态: processing, completed, failed

    # 关联到上传此知识库文件的用户
    uploader = relationship("User")
    # 一个知识库上传操作会产生多个文档块
    document_chunks = relationship("DocumentChunk", back_populates="knowledge_upload", cascade="all, delete-orphan",
                                   passive_deletes=True)

    # 新增: 关联到存储的原始文件实体 (StoredFile)
    # 这样可以从 KnowledgeUpload 记录追溯到 StoredFile 记录
    # 并且在删除 KnowledgeUpload 时，可以选择是否也删除 StoredFile
    stored_file_id = Column(String, ForeignKey("stored_files.id"), nullable=True, index=True)
    # stored_file = relationship("StoredFile", backref="knowledge_uploads") # 如果需要双向关系


class User(Base):
    __tablename__ = "users"  # 用户表
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    sessions = relationship("Session", back_populates="user")
    messages = relationship("Message", back_populates="user")
    session_document_chunks = relationship("DocumentChunk", back_populates="user")
    # 一个用户可以上传多个 StoredFile (包括知识库文件和会话文件)
    stored_files = relationship("StoredFile", back_populates="uploader")


class Session(Base):
    __tablename__ = "sessions"  # 聊天会话表
    id = Column(String, primary_key=True, default=generate_uuid_str, index=True)  # 会话ID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 所属用户ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())  # 创建时间

    user = relationship("User", back_populates="sessions")
    # 一个会话包含多个消息，删除会话时级联删除消息
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan", passive_deletes=True)
    # 一个会话可以包含多个文档块(特指会话上下文文件产生的块)，删除会话时级联删除这些块
    document_chunks = relationship("DocumentChunk", back_populates="session", cascade="all, delete-orphan",
                                   passive_deletes=True)
    # 一个会话可以关联多个原始上传文件 StoredFile (特指会话中上传的文件)
    # 删除会话时，通过 cascade 级联删除关联的 StoredFile 记录
    stored_files = relationship("StoredFile", back_populates="session", cascade="all, delete-orphan",
                                passive_deletes=True)


class Message(Base):
    __tablename__ = "messages"  # 聊天消息表
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)  # 所属会话ID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 发送者ID (助手消息则为 NULL)
    role = Column(String, nullable=False)  # 角色 ('user' or 'assistant')
    content = Column(Text, nullable=False)  # 消息内容
    timestamp = Column(DateTime(timezone=True), server_default=func.now())  # 时间戳

    session = relationship("Session", back_populates="messages")
    user = relationship("User", back_populates="messages")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"  # 文档块表 (用于RAG)
    id = Column(String, primary_key=True, default=generate_uuid_str, index=True)  # 块ID

    # 关联到知识库上传批次 (如果是知识库文件产生的块)
    upload_id = Column(String, ForeignKey("knowledge_uploads.id", ondelete="CASCADE"), nullable=True, index=True)
    # 关联到特定会话 (如果是会话文件产生的块)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)

    document_source = Column(String, nullable=False, index=True)  # 原始文件名
    chunk_index = Column(Integer, nullable=False)  # 块在原文件中的索引
    content = Column(Text, nullable=False)  # 块内容 (文本)
    metadata_json = Column(Text, nullable=True)  # 存储 Langchain Doc 元数据的 JSON 字符串
    added_at = Column(DateTime(timezone=True), server_default=func.now())  # 添加时间

    knowledge_upload = relationship("KnowledgeUpload", back_populates="document_chunks")
    session = relationship("Session", back_populates="document_chunks")
    # 可选: 添加 user_id 以便直接知道添加者 (如果块的添加者和文件上传者可能不同)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("User", back_populates="session_document_chunks")


class StoredFile(Base):
    __tablename__ = "stored_files"  # 存储上传的原始文件表

    id = Column(String, primary_key=True, default=generate_uuid_str, index=True)  # 文件存储记录的ID
    original_filename = Column(String, nullable=False, index=True)  # 原始文件名
    file_type = Column(String, nullable=False)  # 文件MIME类型或扩展名
    file_content = Column(LargeBinary, nullable=False)  # 实际文件内容 (二进制)
    content_length = Column(Integer, nullable=True)  # 文件大小（字节）
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())  # 上传时间
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 上传者ID

    # session_id 为 NULL 表示这是一个全局知识库文件
    # session_id 有值 表示这是一个特定会话的上下文文件
    # 当关联的会话被删除时，由于 ondelete="CASCADE"，这条记录也会被删除
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)

    uploader = relationship("User", back_populates="stored_files")
    session = relationship("Session", back_populates="stored_files")
