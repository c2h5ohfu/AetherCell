from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import Annotated

from api import schemas, security
from api.dependencies import get_db_session
from database import crud, models

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
FormDataDep = Annotated[OAuth2PasswordRequestForm, Depends()]
ActiveUserDep = Annotated[models.User, Depends(security.get_current_active_user)]


@router.post("/register", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(
    user: schemas.UserCreate,
    db: DBSessionDep,
):
    """用户注册"""
    db_user = await crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = security.get_password_hash(user.password)
    user_internal = schemas.UserCreateInternal(
        username=user.username,
        hashed_password=hashed_password
    )
    created_user = await crud.create_user(db=db, user=user_internal)
    # 使用 UserRead schema 返回，避免暴露密码哈希
    return schemas.UserRead.model_validate(created_user) # Pydantic V2

@router.post("/login", response_model=schemas.Token)
async def login_for_access_token(
    form_data: FormDataDep,
    db: DBSessionDep,
):
    """用户登录, 获取 JWT Token"""
    user = await security.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = security.create_access_token(
        data={"sub": user.username} # 使用 username 作为 subject
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/users/me", response_model=schemas.UserRead)
async def read_users_me(
    current_user: ActiveUserDep
):
    """获取当前用户信息(需要认证)"""
    # current_user 已经是 User 模型实例，并且通过了 get_current_active_user 依赖
    # Pydantic V2 使用 model_validate
    return schemas.UserRead.model_validate(current_user)