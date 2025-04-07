from typing import Annotated, TypedDict, List, Dict, Any
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt
from langgraph.prebuilt import ToolNode, tools_condition

# 1. 定义明确的消息结构
class ToolCall(TypedDict):
    name: str
    args: Dict[str, Any]

class Message(TypedDict):
    role: str
    content: str
    tool_calls: List[ToolCall]

class State(TypedDict):
    messages: Annotated[List[Message], lambda x, y: x + [y]]

# 2. 初始化状态图
graph_builder = StateGraph(State)

# 3. 工具定义
@tool
def human_assistance(query: str) -> str:
    """请求人工协助"""
    print(f"\n[系统] 需要人工审核的问题: {query}")
    response = interrupt({"query": query})
    return response["data"]

@tool
def mock_search(query: str) -> str:
    """模拟搜索工具"""
    return f"关于'{query}'的模拟搜索结果"

tools = [mock_search, human_assistance]

# 4. 完全重写的chatbot节点
def chatbot(state: State):
    # 确保messages存在且不为空
    if not state.get("messages") or not isinstance(state["messages"], list):
        return {"messages": [{
            "role": "assistant", 
            "content": "请先发送您的请求",
            "tool_calls": []
        }]}
    
    # 获取最后一条消息（确保是字典）
    last_msg = state["messages"][-1] if state["messages"] else {}
    if not isinstance(last_msg, dict):
        last_msg = {"role": "user", "content": str(last_msg), "tool_calls": []}
    
    # 安全获取内容
    content = last_msg["content"] if "content" in last_msg else ""
    
    # 决策逻辑
    if "帮助" in content:
        return {"messages": [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "name": "human_assistance",
                "args": {"query": content}
            }]
        }]}
    else:
        return {"messages": [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "name": "mock_search",
                "args": {"query": content}
            }]
        }]}

# 5. 构建图
graph_builder.add_node("chatbot", chatbot)
graph_builder.add_node("tools", ToolNode(tools))

graph_builder.add_edge(START, "chatbot")
graph_builder.add_conditional_edges(
    "chatbot",
    tools_condition,
)
graph_builder.add_edge("tools", "chatbot")

# 6. 编译工作流
memory = MemorySaver()
workflow = graph_builder.compile(checkpointer=memory)

# 7. 改进的测试函数
def run_example():
    # 测试用例1: 需要人工协助的请求
    print("=== 测试1: 需要人工协助的请求 ===")
    thread_id = "thread_123"
    config = {"configurable": {"thread_id": thread_id}}
    
    # 准备输入消息（确保格式正确）
    input_msg = {
        "messages": [
            {"role": "user", "content": "我需要帮助", "tool_calls": []}
        ]
    }
    
    # 执行工作流
    for output in workflow.stream(input_msg, config=config):
        for key, value in output.items():
            if key == "__end__":
                continue
            
            # 打印消息（确保处理字典格式）
            if isinstance(value, list):
                for msg in value:
                    if isinstance(msg, dict):
                        print(f"\n[角色]: {msg.get('role', '未知')}")
                        print(f"[内容]: {msg.get('content', '')}")
                        if "tool_calls" in msg:
                            for call in msg["tool_calls"]:
                                print(f"[工具调用]: {call.get('name', '未知工具')}")
            
            # 检查中断
            state = workflow.get_state(config)
            if state and state.next == ("tools",):
                print("\n[系统] 流程已暂停，等待人工输入...")
                human_input = input("请输入协助内容: ")
                workflow.invoke(
                    {"messages": [{"role": "user", "content": human_input, "tool_calls": []}]},
                    config=config
                )
                return
    
    # 测试用例2: 自动处理的请求
    print("\n=== 测试2: 自动处理的请求 ===")
    workflow.invoke(
        {"messages": [{"role": "user", "content": "普通查询", "tool_calls": []}]},
        config={"configurable": {"thread_id": "thread_456"}}
    )

if __name__ == "__main__":
    run_example()