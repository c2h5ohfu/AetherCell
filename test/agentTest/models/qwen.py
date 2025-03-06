from langchain_ollama import ChatOllama

qwen = ChatOllama(model = "qwen2.5:7b")


if __name__ == '__main__':
    print(qwen.invoke("hello"))