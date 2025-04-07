from typing import Annotated, Dict, Any, List
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from typing_extensions import TypedDict
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command, interrupt


class State(TypedDict):
    messages: Annotated[List[Dict[str, Any]], add_messages]


# 模拟的AI模型响应
class MockAIModel:
    def __init__(self):
        self.tools = []
    
    def bind_tools(self, tools):
        self.tools = tools
        return self
    
    def invoke(self, messages):
        last_message = messages[-1]
        last_content = last_message.content if hasattr(last_message, 'content') else str(last_message)
        
        # 检查是否是工具消息（专家回复）
        if isinstance(last_message, ToolMessage):
            return AIMessage(
                content=f"收到专家回复，感谢专家的建议。",
                tool_calls=[]
            )
        
        # 模拟AI模型的决策逻辑
        if "专家" in last_content or "帮助" in last_content or "指导" in last_content:
            # 需要专家帮助的情况
            return AIMessage(
                content="这个问题可能需要专家的意见，让我请求专家协助。",
                tool_calls=[{
                    "name": "human_assistance",
                    "args": {"query": f"用户询问：{last_content}\n需要专家建议，请提供专业意见。"},
                    "id": "call_expert"
                }]
            )
        elif "时间" in last_content or "日期" in last_content or "几点" in last_content:
            # 模拟时间相关回答
            return AIMessage(
                content="我可以回答时间相关的问题，但我是一个模拟的AI模型，建议使用真实的时间处理工具。",
                tool_calls=[]
            )
        elif "谢谢" in last_content or "感谢" in last_content:
            return AIMessage(
                content="不客气！如果还有其他问题，随时告诉我。",
                tool_calls=[]
            )
        else:
            # 模拟通用回答
            return AIMessage(
                content=f"我理解您的问题是关于'{last_content}'。作为一个模拟的AI模型，我建议您使用真实的AI模型来获得更好的回答。如果您需要专家建议，可以直接说'需要专家帮助'。",
                tool_calls=[]
            )


# 创建人机交互工具
@tool
def human_assistance(query: str) -> str:
    """Request assistance from a human expert."""
    print(f"\n[System] === 需要专家协助 ===")
    print(f"问题详情: {query}")
    print("\n[System] 请专家输入建议或回复 (输入后按回车):")
    human_response = input("> ")
    return f"专家回复: {human_response}"


# 初始化图和模型
graph_builder = StateGraph(State)
tools = [human_assistance]
mock_llm = MockAIModel().bind_tools(tools)


# 模拟聊天机器人节点
def chatbot(state: State):
    messages = state["messages"]
    message = mock_llm.invoke(messages)
    
    # 确保每次只调用一个工具（简化处理）
    if hasattr(message, 'tool_calls') and len(message.tool_calls) > 1:
        message.tool_calls = [message.tool_calls[0]]
    
    return {"messages": [message]}


# 构建图
graph_builder.add_node("chatbot", chatbot)
tool_node = ToolNode(tools=tools)
graph_builder.add_node("tools", tool_node)

graph_builder.add_conditional_edges(
    "chatbot",
    tools_condition,
)
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")

memory = MemorySaver()
graph = graph_builder.compile(checkpointer=memory)


# 辅助函数，用于打印消息
def print_message(message):
    if isinstance(message, HumanMessage):
        print(f"\n用户: {message.content}")
    elif isinstance(message, AIMessage):
        print(f"\nAI: {message.content}")
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for call in message.tool_calls:
                print(f"  - 调用工具: {call['name']}")
    elif isinstance(message, ToolMessage):
        print(f"\n工具响应: {message.content}")


def interactive_chat():
    """交互式聊天主循环"""
    print("\n=== 欢迎使用AI助手 ===")
    print("输入 'quit' 或 'exit' 退出对话")
    
    config = {"configurable": {"thread_id": "interactive"}}
    
    while True:
        try:
            # 获取用户输入
            user_input = input("\n请输入您的消息: ")
            
            # 检查是否退出
            if user_input.lower() in ['quit', 'exit']:
                print("\n感谢使用，再见！")
                break
            
            # 处理用户输入
            events = graph.stream(
                {"messages": [HumanMessage(content=user_input)]},
                config,
                stream_mode="values",
            )
            
            # 显示响应
            for event in events:
                if "messages" in event:
                    last_msg = event["messages"][-1]
                    print_message(last_msg)
                    
        except KeyboardInterrupt:
            print("\n\n检测到 Ctrl+C，正在退出...")
            break
        except Exception as e:
            print(f"\n发生错误: {str(e)}")
            print("请重试或输入 'quit' 退出")


if __name__ == "__main__":
    interactive_chat()