# api/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from starlette.staticfiles import StaticFiles

# 导入主数据库的初始化和清理
from database.database import init_db as init_main_db, dispose_engine as dispose_main_engine
from api.routers import auth, chat, files

load_dotenv()
# --- 静态文件和前端配置 ---

# 确定项目根目录的更可靠方法
# __file__ 是当前文件 (main.py) 的路径
# os.path.dirname(__file__) 是 api/ 目录
# os.path.dirname(os.path.dirname(__file__)) 是项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 前端打包文件的主目录 (例如: your_project_root/static/dist)
STATIC_DIST_DIR = os.path.join(PROJECT_ROOT, "static", "dist")

# 生成图片的保存目录 (例如: your_project_root/generated_plots)
GENERATED_PLOTS_DIR = os.path.join(PROJECT_ROOT, "generated_plots")


 # CORS 配置
# origins = [
# ]

# 简化 Lifespan: 只处理主数据库
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_main_db()
    yield # 应用运行
    await dispose_main_engine()
app = FastAPI(
    title="MetherX",
    description="with multi-agent",
    version="0.1.0",
    lifespan=lifespan
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
   # allow_origins=origins,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 包含路由
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(files.router)


# --- 挂载静态文件 ---

# 1. 挂载用于保存生成图片的目录
#    URL 路径: /static_generated_plots/your_image.png
#    文件系统路径: your_project_root/generated_plots/your_image.png
app.mount(f"/static_generated_plots", StaticFiles(directory=GENERATED_PLOTS_DIR), name="generated_plots")

# 2. 挂载前端应用的静态文件 (位于 static/dist/)
#    这将使得 static/dist/ 目录下的所有文件都可以通过相对于根 URL 的路径访问
#    例如, static/dist/assets/index-xxxx.js 将通过 /assets/index-xxxx.js 访问
#    重要的是 index.html 也在这个目录下。
#    我们将这个挂载到根路径 "/"。
#    `html=True` 会让 FastAPI 尝试为 "/" 这样的路径提供 "index.html"。
#    这个挂载应该在所有API路由之后，或者API路由有明确前缀（目前是这样）。
app.mount("/", StaticFiles(directory=STATIC_DIST_DIR, html=True), name="static_frontend_root")


# --- SPA 路由回退 (如果 StaticFiles(html=True) 不够用或需要更精细控制) ---
# 对于许多现代打包工具生成的SPA，html=True 可能已经足够处理根 index.html。
# 但是，如果前端路由（如 /dashboard, /profile）在刷新页面时返回404，
# 那么你仍然需要一个回退路由来将这些路径指向 index.html。
# 注意：如果上面的 app.mount("/", StaticFiles(..., html=True)) 已经处理了所有情况，
# 这个回退路由可能不会被触发，或者您可以根据需要调整。

@app.exception_handler(404) # 捕获404错误
async def spa_fallback(request: Request, exc): # exc 是 HTTPException
    # 仅当请求看起来是针对前端路由时才返回index.html
    # 避免将API的404也重定向到index.html
    # 一个简单的检查是看请求头是否接受html
    if "text/html" in request.headers.get("accept", ""):
        index_path = os.path.join(STATIC_DIST_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    # 否则，返回标准的API 404响应
    return JSONResponse(
        status_code=404,
        content={"detail": f"资源未找到: {request.url.path}"},
    )


# 全局异常处理
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):

    print(f"未处理的异常: {exc}", flush=True)
    import traceback
    traceback.print_exc()
    return JSONResponse( status_code=500, content={"detail": "服务器内部错误"},)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):

    return JSONResponse( status_code=422, content={"detail": exc.errors()},)

# 根路径
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "MetherX"}