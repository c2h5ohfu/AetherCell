# AetherCell_Agent
## 项目目录
```
├── src/
│   ├── agent/
│   ├── app/
│   ├── models/
│   └── tools/
└── test/
    ├── agentic_rag_demo.ipynb           langgraph 实现agentic rag
    ├── agentTest/
    │   ├── agentdemo/
    │   ├── models/
    │   ├── resources/
    │   └── tools/
    ├── demo/                            一个fastapi的demo
    │   ├── __init__.py
    │   ├── agentDemo.py
    │   └── fastapiDemo.py
    └── winter/                          寒假实现的前后端分离的demo
        ├── SimpleBackend.py
        ├── SimpleFrontend.py
        └── picture/

```
## 快速启动

```
pip install requirements.txt
```

winter：
一定要到对应项目文件下启动

后端启动
```
uvicorn SimpleBackend:app --reload
```
前端启动
```
strealit run SimpleFrontend.py
```