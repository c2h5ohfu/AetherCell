# api/schemas.py
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing_extensions import List, Optional
from datetime import datetime
import json

# --- User Schemas ---
class UserBase(BaseModel): username: str
class UserCreate(UserBase): password: str
class UserCreateInternal(UserBase): hashed_password: str
class UserRead(UserBase): id: int; model_config = ConfigDict(from_attributes=True)

# --- Token Schemas ---
class Token(BaseModel): access_token: str; token_type: str
class TokenData(BaseModel): username: Optional[str] = None

# --- Session Schemas ---
class SessionRead(BaseModel): id: str; user_id: int; created_at: datetime; model_config = ConfigDict(from_attributes=True)
class ListSessionsResponse(BaseModel): sessions: List[SessionRead]

# --- Message Schemas ---
class MessageBase(BaseModel): role: str; content: str
class MessageCreate(BaseModel): content: str
class MessageCreateDB(MessageBase): session_id: str; user_id: Optional[int] = None
class MessageRead(MessageBase):
    id: int
    session_id: str
    user_id: Optional[int] = None
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)


# --- Knowledge Upload Schemas ---
class KnowledgeUploadBase(BaseModel):
    original_filename: str

class KnowledgeUploadCreate(KnowledgeUploadBase):
    uploader_id: int
    stored_file_id: str # 新增: 关联到已存储的 StoredFile 记录的 ID

class KnowledgeUploadRead(KnowledgeUploadBase):
    id: str # KnowledgeUpload 记录自身的 ID
    uploader_id: int
    uploaded_at: datetime
    status: str
    stored_file_id: Optional[str] = None # 从数据库模型中读取时也包含它
    model_config = ConfigDict(from_attributes=True)

class ListKnowledgeUploadsResponse(BaseModel):
    uploads: List[KnowledgeUploadRead]

class KnowledgeUploadResponse(BaseModel): # API 端点成功上传知识库文件后的响应
    filename: str
    message: str
    upload_id: str # KnowledgeUpload 记录的 ID
    upload_type: str = "knowledge"
    stored_file_id: Optional[str] = None # StoredFile 记录的 ID


# --- Session File Upload Schemas ---
class SessionFileUploadResponse(BaseModel): # API 端点成功上传会话文件后的响应
    filename: str
    message: str
    upload_type: str = "session"
    assistant_acknowledgment: Optional[str] = Field(None, description="AI 对文件接收的确认回复。")
    chunk_count: int
    stored_file_id: Optional[str] = None # StoredFile 记录的 ID (如果会话文件也存入StoredFile)


# --- Document Chunk Schemas ---
class DocumentChunkBase(BaseModel):
    document_source: str
    chunk_index: int
    content: str
    metadata_json: Optional[str] = None
    upload_id: Optional[str] = None # 指向 KnowledgeUpload.id (知识库文件)
    session_id: Optional[str] = None # 指向 Session.id (会话文件)

class DocumentChunkCreate(DocumentChunkBase):
    id: str # DocumentChunk 自身的 ID
    @model_validator(mode='before')
    @classmethod
    def check_link_exclusive(cls, values):
        upload_id = values.get('upload_id')
        session_id = values.get('session_id')
        if (upload_id is None and session_id is None):
            raise ValueError('文档块必须关联到 upload_id 或 session_id。')
        if (upload_id is not None and session_id is not None):
            raise ValueError('文档块不能同时关联到 upload_id 和 session_id。')
        return values

class DocumentChunkRead(DocumentChunkBase):
    id: str
    added_at: datetime
    user_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)
    @field_validator('metadata_json', mode='before')
    @classmethod
    def parse_metadata_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                print(f"警告: 无法解析元数据 JSON: {v}")
                return None
        return v

# --- Delete Response Schema ---
class DeleteResponse(BaseModel):
    success: bool
    message: str


# --- Stored File Schemas ---
class StoredFileBase(BaseModel):
    original_filename: str
    file_type: str # MIME type or simple extension
    content_length: Optional[int] = None

class StoredFileCreate(StoredFileBase): # 用于API接收文件元数据，实际文件内容分开处理
    uploader_id: int
    session_id: Optional[str] = None # 用于区分知识库文件 (None) 和会话文件 (session_id)

class StoredFileRead(StoredFileBase): # 用于从数据库读取和API响应
    id: str
    uploader_id: int
    uploaded_at: datetime
    session_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)