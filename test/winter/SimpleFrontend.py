import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import requests
API_URL = "http://localhost:8000"
# 1. 设置页面配置，必须在所有其他 Streamlit 命令之前调用
st.set_page_config(
    page_title="AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://www.deepseek.com/',
        'Report a bug': 'https://www.deepseek.com/',
        'About': "# AI\n "
    }
)

# 2. 将本地图片转换为 Base64 编码的字符串
def get_image_as_base64(image_path):
    try:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
        return f"data:image/png;base64,{encoded_string}"
    except Exception as e:
        st.error(f"无法加载图片 {image_path}: {e}")
        return ""

# 定义用户和AI的头像路径
USER_AVATAR_PATH = "./picture/DaShu.jpg"         # 替换为您的用户头像文件名
ASSISTANT_AVATAR_PATH = "./picture/DaShu.jpg"    # 替换为您的 AI 头像文件名

# 获取头像的 Base64 编码字符串
USER_AVATAR_BASE64 = get_image_as_base64(USER_AVATAR_PATH)
ASSISTANT_AVATAR_BASE64 = get_image_as_base64(ASSISTANT_AVATAR_PATH)

# 3. 自定义 CSS 固定输入框在底部
st.markdown(
    """
    <style>
    /* 固定输入框在底部 */
    .fixed-bottom {
        position: fixed;
        bottom: 0;
        left: 0;
        width: 100%;
        background-color: white;
        padding: 10px;
        box-shadow: 0 -2px 5px rgba(0,0,0,0.1);
    }
    /* 调整主内容区域的底部内边距，避免输入框遮挡内容 */
    .reportview-container .main {
        padding-bottom: 100px;
    }
    .chat-container {
        display: flex;
        align-items: flex-start;
        margin-bottom: 10px;
    }
    .avatar {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        margin-right: 10px;
    }
    .message {
        background-color: #f1f0f0;
        padding: 10px 15px;
        border-radius: 10px;
        max-width: 80%;
    }
    .user .message {
        background-color: #c3d7df;
    }
    .assistant .message {
        background-color: #f1f0f0;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# 4. 文件解析功能
def parse_file(file):
    try:
        df = pd.read_excel(file)
        summary = f"文件包含 {df.shape[0]} 行和 {df.shape[1]} 列。数据的一部分：\n{df.head().to_string(index=False)}"
        return summary, df
    except Exception as e:
        return f"无法解析Excel文件: {e}", None

# 5. 初始化会话状态
if 'messages' not in st.session_state:
    st.session_state.messages = []

if 'df' not in st.session_state:
    st.session_state.df = None

if 'file_info' not in st.session_state:
    st.session_state.file_info = ""
    st.session_state.file_uploaded = False

# 6. 页面布局
st.title("🫨AI")
st.markdown("""
您可以与 AI 进行对话，上传 Excel 文件并生成相关图表。
""")

# 7. 侧边栏：上传文件
st.sidebar.header("😋文件上传与图表生成")
st.sidebar.write("""
1. 上传一个 `.xlsx` 文件。
2. 查看文件的基本信息和数据预览。
3. 选择图表类型（柱状图或折线图）并生成图表。
4. 在主对话区与 AI 进行交流。
""")

uploaded_file = st.sidebar.file_uploader("上传一个Excel文件", type=["xlsx"])

if uploaded_file is not None:
    file_info, df = parse_file(uploaded_file)
    st.sidebar.write(file_info)
    if df is not None:
        st.session_state.df = df
        st.session_state.file_uploaded = True
        st.sidebar.write("数据预览：")
        st.sidebar.dataframe(df.head())

        # 将文件信息存储在独立的变量中，而不是添加到对话历史
        st.session_state.file_info = f"我刚刚上传了一个文件，内容概述如下：\n{file_info}"

        # 调用后端生成回复
        with st.spinner("AI 正在分析文件内容..."):
            # 构建请求数据
            messages = st.session_state.messages + [{"role": "user", "content": st.session_state.file_info}]
            response = requests.post(f"{API_URL}/chat", json={"messages": messages})
            if response.status_code == 200:
                ai_reply = response.json()["content"]
                st.session_state.messages.append({"role": "assistant", "content": ai_reply})
            else:
                st.error(f"AI 回复失败: {response.json().get('detail', '未知错误')}")

        # 选择图表类型
        plot_type = st.sidebar.selectbox("选择图表类型", ["柱状图", "折线图"])
        if st.sidebar.button("生成图表"):
            if st.session_state.df is not None:
                with st.spinner(f"正在生成{plot_type}..."):
                    # 准备数据
                    data = st.session_state.df.head().to_dict(orient='records')
                    # 发送生成图表请求
                    plot_response = requests.post(
                        f"{API_URL}/generate_plot",
                        json={"data": data, "plot_type": "bar" if plot_type == "柱状图" else "line"}
                    )
                    if plot_response.status_code == 200:
                        img_base64 = plot_response.json()["image_base64"]
                        # 添加用户反馈消息
                        st.session_state.messages.append({"role": "user", "content": f"已生成{plot_type}并显示。"})

                        # 构建AI的回复消息，包含图表
                        ai_content = f"{plot_type}已成功生成并显示。<br><img src='data:image/png;base64,{img_base64}' alt='{plot_type}'/>"
                        st.session_state.messages.append({"role": "assistant", "content": ai_content})
                        st.sidebar.success(f"已生成{plot_type}并显示。")
                    else:
                        st.error(f"图表生成失败: {plot_response.json().get('detail', '未知错误')}")
            else:
                st.warning("请先上传有效的Excel文件。")

    # 添加“清除上传的文件”按钮
    if st.session_state.file_uploaded:
        if st.sidebar.button("清除上传的文件"):
            st.session_state.df = None
            st.session_state.file_uploaded = False
            st.session_state.file_info = ""
            # 清除与文件相关的对话历史
            st.session_state.messages = [msg for msg in st.session_state.messages if not ("我刚刚上传了一个文件" in msg["content"])]
            st.sidebar.success("已清除上传的文件。")

# 8. 主对话区

# 使用一个容器来包裹对话记录，确保其可滚动
chat_container = st.container()
with chat_container:
    for msg in st.session_state.messages:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            avatar_url = USER_AVATAR_BASE64
        else:
            avatar_url = ASSISTANT_AVATAR_BASE64

        # 构建带头像的消息
        message_html = f"""
        <div class="chat-container {role}">
            <img src="{avatar_url}" class="avatar">
            <div class="message">{content}</div>
        </div>
        """
        st.markdown(message_html, unsafe_allow_html=True)

# 9. 固定在底部的输入框使用 st.chat_input
user_input = st.chat_input("😋输入你的消息 (输入 '退出' 来结束对话)")

if user_input:
    if user_input.strip().lower() == "退出":
        st.session_state.messages = []
        st.session_state.df = None
        st.session_state.file_info = ""
        st.session_state.file_uploaded = False
        st.sidebar.success("对话历史已清除。")
        end_message = {"role": "assistant", "content": "对话结束。您可以重新开始。"}

        # 显示结束消息
        end_message_html = f"""
        <div class="chat-container assistant">
            <img src="{ASSISTANT_AVATAR_BASE64}" class="avatar">
            <div class="message">{end_message['content']}</div>
        </div>
        """
        chat_container.markdown(end_message_html, unsafe_allow_html=True)
    else:
        # 添加用户消息到消息列表
        user_message = {"role": "user", "content": user_input}
        st.session_state.messages.append(user_message)

        # 显示用户消息
        user_message_html = f"""
        <div class="chat-container user">
            <img src="{USER_AVATAR_BASE64}" class="avatar">
            <div class="message">{user_input}</div>
        </div>
        """
        chat_container.markdown(user_message_html, unsafe_allow_html=True)

        # 调用后端生成回复
        with st.spinner("AI 正在回复..."):
            response = requests.post(f"{API_URL}/chat", json={"messages": st.session_state.messages})
            if response.status_code == 200:
                ai_reply = response.json()["content"]
                ai_message = {"role": "assistant", "content": ai_reply}
                st.session_state.messages.append(ai_message)
            else:
                ai_reply = f"AI 回复失败: {response.json().get('detail', '未知错误')}"
                ai_message = {"role": "assistant", "content": ai_reply}
                st.session_state.messages.append(ai_message)

        # 显示AI回复
        ai_message_html = f"""
        <div class="chat-container assistant">
            <img src="{ASSISTANT_AVATAR_BASE64}" class="avatar">
            <div class="message">{ai_reply}</div>
        </div>
        """
        chat_container.markdown(ai_message_html, unsafe_allow_html=True)
