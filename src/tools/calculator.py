from tools_sdk import tool

@tool(description="Adds two numbers together")
def add(a: float, b: float) -> float:
    return a + b

@tool(description="Multiplies two numbers")
def multiply(a: float, b: float) -> float:
    return a * b
