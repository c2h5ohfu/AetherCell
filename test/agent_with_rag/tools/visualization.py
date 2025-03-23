from typing import Annotated
from langchain_experimental.utilities import PythonREPL
from langchain_core.tools import tool
import matplotlib.pyplot as plt
import io
import base64

repl = PythonREPL()

@tool
def python_repl(code: Annotated[str, "The python code to execute to generate your chart."]):
    """
    如果用户要求对文件进行绘图时，接受大模型返回的python代码
    Execute python code. Print output to see the result, which will be visible to the user.
    If the code generates a plot, save it to a file and return the file path.
    """
    try:
        # 捕获标准输出和图像
        result = repl.run(code)

        # 检查是否生成了图像
        if plt.fignum_exists(1):  # 检查是否存在活动图像
            # 保存图像到内存
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png')
            plt.close()

            # 将图像编码为Base64
            img_buffer.seek(0)
            img_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')

            # 返回图像的Base64编码
            return f"Successfully executed:\n```python\n{code}\n```\nImage: ![](data:image/png;base64,{img_base64})\n\nIf you have completed all tasks, respond with FINAL ANSWER."
        else:
            # 没有生成图像，直接返回结果
            return f"Successfully executed:\n```python\n{code}\n```\nStdout: {result}\n\nIf you have completed all tasks, respond with FINAL ANSWER."

    except BaseException as e:
        return f"Failed to execute. Error: {repr(e)}"

