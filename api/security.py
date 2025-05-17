# api/security.py
import os
from datetime import datetime, timedelta, timezone
from typing_extensions import Optional, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

# 使用绝对导入
from database import crud, models
from api import schemas
from api.dependencies import get_db_session

load_dotenv()

# Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
if not JWT_SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY must be set in the environment variables")

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# JWT Token Handling
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login") # 指向登录路由

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

# User Authentication
async def authenticate_user(db: AsyncSession, username: str, password: str) -> Optional[models.User]:
    """验证用户凭据 (添加了调试日志)"""
    print(f"==> [Auth] authenticate_user called for username: {username}")
    user = await crud.get_user_by_username(db, username=username)
    if not user:
        print(f"==> [Auth] User '{username}' not found in database.")
        return None
    is_password_correct = verify_password(password, user.hashed_password)
    print(f"==> [Auth] Password verification result for user '{username}': {is_password_correct}")
    if not is_password_correct:
        return None
    print(f"==> [Auth] Authentication successful for user '{username}'.")
    return user

# Dependency for Current User
DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]

async def get_current_user(token: TokenDep, db: DBSessionDep) -> models.User:
    """解码JWT, 验证 token, 并从数据库获取当前用户 (添加了调试日志)"""
    credentials_exception = HTTPException( status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"}, )
    print(f"==> [get_current_user] Received raw token: {token[:10]}...{token[-10:]}")
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        print(f"==> [get_current_user] Decoded payload: {payload}")
        username: Optional[str] = payload.get("sub")
        if username is None:
            print("==> [get_current_user] Error: 'sub' field (username) not found in token payload.")
            raise credentials_exception
        token_data = schemas.TokenData(username=username)
    except JWTError as e:
        print(f"==> [get_current_user] JWTError decoding token: {e}")
        raise credentials_exception
    except Exception as e_decode:
        print(f"==> [get_current_user] Unexpected error decoding token: {e_decode}")
        raise credentials_exception

    print(f"==> [get_current_user] Looking up user: {token_data.username}")
    user = await crud.get_user_by_username(db, username=token_data.username)
    if user is None:
        print(f"==> [get_current_user] Error: User '{token_data.username}' not found in database.")
        raise credentials_exception
    print(f"==> [get_current_user] User '{user.username}' validated successfully.")
    return user

CurrentUserDep = Annotated[models.User, Depends(get_current_user)]

async def get_current_active_user(current_user: CurrentUserDep) -> models.User:
    # 可选：检查用户是否被禁用等
    # if current_user.disabled:
    #     raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

ActiveUserDep = Annotated[models.User, Depends(get_current_active_user)]