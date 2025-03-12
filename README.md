# AetherCell_Agent



## 前言

> ***"In the cosmology of ancient Greece, αἰθήρ (Aether) was the pure breath of Olympian deities — an immortal essence that nourished celestial bodies. It was neither air nor fire, but the fifth element that whispered eternity into the veins of cosmos.***
>
> ***In 1873, James Clerk Maxwell wrote: 'The aether is as real as the air we breathe.'***
> 
>
> ***Today, we redefined its reality – not as a medium for light, but as a sentinel for energy."***

 ## 项目目录

```
├── src/
│   ├── agent/
│   ├── app/
│   ├── models/                          
│   └── tools/
└── test/
    ├── agentic_rag_demo.ipynb
    ├── agentTest/
    │   ├── agentdemo/
    │   ├── models/
    │   ├── resources/
    │   └── tools/
    ├── demo/
    │   ├── __init__.py
    │   ├── agentDemo.py
    │   └── fastapiDemo.py
    └── winter/
        ├── SimpleBackend.py
        ├── SimpleFrontend.py
        └── picture/

```
## 快速启动

```
pip install -r requirements.txt
```



### src/

在models包下可以选择本地大模型

tools包下可以调用or自定义工具

启动时不要忘记修改aethercell.py中的llm、tools配置



### Test/

demo、winter包下的前后端分离项目：

命令行启动时一定要位于当前文件的目录下，将`your_name`改为相应的文件名，如果没有位于启动文件所在的目录，请将`your_name`改为文件所在目录的相对路径



后端启动
```
uvicorn your_name:app --reload
```
前端启动
```
strealit run your_name.py
```