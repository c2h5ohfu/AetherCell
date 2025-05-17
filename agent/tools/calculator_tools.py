# agent/tools/calculator_tools.py
from langchain_core.tools import tool
import logging

logger = logging.getLogger(__name__)

@tool
async def add(a: float, b: float) -> float:
    """计算两个数字的和。例如: add(a=1, b=2) -> 3"""
    logger.info(f"执行加法: {a} + {b}")
    return a + b

@tool
async def subtract(a: float, b: float) -> float:
    """计算两个数字的差。例如: subtract(a=5, b=2) -> 3"""
    logger.info(f"执行减法: {a} - {b}")
    return a - b

@tool
async def multiply(a: float, b: float) -> float:
    """计算两个数字的乘积。例如: multiply(a=3, b=4) -> 12"""
    logger.info(f"执行乘法: {a} * {b}")
    return a * b

@tool
async def divide(a: float, b: float) -> float | str:
    """
    计算两个数字的商。如果除数为零，则返回错误信息。
    例如: divide(a=10, b=2) -> 5
    例如: divide(a=5, b=0) -> '错误：除数不能为零。'
    """
    logger.info(f"执行除法: {a} / {b}")
    if b == 0:
        logger.warning("除法错误：除数为零")
        return "错误：除数不能为零。"
    return a / b

# 将所有计算工具放入列表，方便 Agent 使用
calculator_tools = [add, subtract, multiply, divide]