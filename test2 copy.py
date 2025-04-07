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
        
        # 模拟根据用户输入决定是否调用工具
        if "request assistance" in last_content.lower() or "expert guidance" in last_content.lower():
            # 模拟调用human_assistance工具
            return AIMessage(
                content="I'll request human assistance for you.",
                tool_calls=[{
                    "name": "human_assistance",
                    "args": {"query": "A user is requesting expert guidance for building an AI agent. Could you please provide some expert advice or resources on this topic?"},
                    "id": "mock_tool_call_id"
                }]
            )
        elif "thank" in last_content.lower():
            # 模拟最终回复
            return AIMessage(
                content="You're welcome! Let me know if you need any further assistance.",
                tool_calls=[]
            )
        else:
            # 模拟普通回复
            return AIMessage(
                content="I'm a mock AI model. I can't actually process your request.",
                tool_calls=[]
            )


# 创建人机交互工具
@tool
def human_assistance(query: str) -> str:
    """Request assistance from a human."""
    print(f"\n[System] Human assistance requested with query: {query}")
    human_response = interrupt({"query": query})
    return human_response["data"]


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
        print(f"User: {message.content}")
    elif isinstance(message, AIMessage):
        print(f"AI: {message.content}")
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for call in message.tool_calls:
                print(f"  - Calling tool: {call['name']} with args: {call['args']}")
    elif isinstance(message, ToolMessage):
        print(f"Tool: {message.content}")


# 测试函数
def test_conversation():
    # 第一轮对话 - 请求帮助
    print("\n=== First Round: Requesting Assistance ===")
    user_input = "I need some expert guidance for building an AI agent. Could you request assistance for me?"
    config = {"configurable": {"thread_id": "1"}}
    
    events = graph.stream(
        {"messages": [HumanMessage(content=user_input)]},
        config,
        stream_mode="values",
    )
    
    for event in events:
        if "messages" in event:
            last_msg = event["messages"][-1]
            print_message(last_msg)
    
    # 检查状态
    snapshot = graph.get_state(config)
    print(f"\nCurrent state: next node = {snapshot.next}")
    
    # 第二轮 - 人工响应
    print("\n=== Second Round: Human Response ===")
    human_response = (
        "We, the experts are here to help! We'd recommend you check out LangGraph to build your agent. "
        "It's much more reliable and extensible than simple autonomous agents."
    )
    
    human_command = Command(resume={"data": human_response})
    
    events = graph.stream(human_command, config, stream_mode="values")
    for event in events:
        if "messages" in event:
            last_msg = event["messages"][-1]
            print_message(last_msg)
    
    # 第三轮 - 感谢
    print("\n=== Third Round: Thanking ===")
    events = graph.stream(
        {"messages": [HumanMessage(content="Thank you for the help!")]},
        config,
        stream_mode="values",
    )
    
    for event in events:
        if "messages" in event:
            last_msg = event["messages"][-1]
            print_message(last_msg)


if __name__ == "__main__":
    test_conversation()