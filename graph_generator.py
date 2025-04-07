from typing import Dict, List, Annotated, TypedDict, Generator
from langchain_core.messages import HumanMessage
from langgraph.graph import Graph, StateGraph
from langchain_openai import ChatOpenAI
from flask import Response
import json
import os
import requests
from urllib.parse import urlparse
from pathlib import Path
from langgraph.types import Command, interrupt

# 定义状态类型
class StoryState(TypedDict):
    outline: str
    story: str
    scenes: List[Dict]
    current_scene_index: int
    completed: bool
    streaming: bool
    approved: bool  # 新增审核状态

# 添加图片存储目录配置
IMAGES_DIR = "static/images"
os.makedirs(IMAGES_DIR, exist_ok=True)

def download_image(url: str, save_dir: str) -> str:
    """下载图片并返回本地路径"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # 从URL生成文件名
        filename = f"{hash(url)}.png"
        local_path = os.path.join(save_dir, filename)
        
        # 保存图片
        with open(local_path, 'wb') as f:
            f.write(response.content)
        
        # 返回相对路径（用于Web访问）
        return f"/static/images/{filename}"
    except Exception as e:
        print(f"下载图片失败: {e}")
        return url  # 如果下载失败，返回原始URL

# 故事生成节点
def generate_story(state: StoryState) -> Generator[StoryState, None, None]:
    llm = ChatOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        model="gpt-3.5-turbo",
        streaming=True
    )
    
    prompt = f"""
    你是一个专业的儿童绘本作家。请根据以下大纲创作一个适合儿童的故事，要求：
    1. 故事生动有趣，富有想象力
    2. 语言简单易懂，适合朗读
    3. 适合3-6岁儿童阅读
    4. 每个场景要有清晰的描写
    5. 故事篇幅适中，200字以内，分3个场景。
    6. 每个场景都要有明确的环境描写，便于后续生成配图
    
    大纲：{state['outline']}
    """
    
    state['story'] = ""
    
    if state['streaming']:
        for chunk in llm.stream([HumanMessage(content=prompt)]):
            content_chunk = chunk.content
            # print(f"Streaming chunk: {content_chunk}")  # 调试日志
            state['story'] += content_chunk
            yield {
                "type": "story_update",
                "content": state['story'],
                "completed": False
            }
        # 最后一次更新，标记完成
        yield {
            "type": "story_update",
            "content": state['story'],
            "completed": True
        }
    else:
        response = llm.invoke([HumanMessage(content=prompt)])
        state['story'] = response.content
        yield state

# 场景分割节点
def split_scenes(state: StoryState) -> StoryState:
    paragraphs = [p.strip() for p in state['story'].split('\n\n') if p.strip()]
    state['scenes'] = []
    
    for paragraph in paragraphs:
        scene = {
            "text": paragraph,
            "prompt": f"童话风格的插图，可爱温馨，{paragraph}",
            "negative_prompt": "人物，黑暗，恐怖，写实风格"
        }
        state['scenes'].append(scene)
    
    state['current_scene_index'] = 0
    return state

# 图片生成节点
def generate_images(state: StoryState) -> StoryState:
    from storybook_generator import StorybookGenerator
    generator = StorybookGenerator()
    
    scene = state['scenes'][state['current_scene_index']]
    image_url = generator.generate_image(scene['prompt'], scene['negative_prompt'])
    
    # 下载并保存图片
    local_image_path = download_image(image_url, IMAGES_DIR)
    scene['image_url'] = local_image_path  # 使用本地路径替换远程URL
    
    state['current_scene_index'] += 1
    if state['current_scene_index'] >= len(state['scenes']):
        state['completed'] = True
    
    return state

# 添加人工审核工具
def human_review(state: StoryState, review_queue=None) -> StoryState:
    """请求人工审核故事内容"""
    print(f"\n[System] 请求人工审核故事内容")
    try:
        
        if review_queue is None:
            print("No review queue provided")
            state["approved"] = False
            return state
            
        # 等待审核结果
        review_data = review_queue.get()  # 从队列中获取审核结果
        print(f"Received review data: {review_data}")
        
        if isinstance(review_data, dict):
            state["approved"] = review_data.get("approved", False)
        else:
            print(f"Unexpected review data type: {type(review_data)}")
            state["approved"] = False
            
    except Exception as e:
        print(f"Error in human review: {e}")
        state["approved"] = False
    
    print(f"Review result: {'Approved' if state['approved'] else 'Rejected'}")
    return state

# 添加结束节点
def end_workflow(state: StoryState) -> StoryState:
    """结束工作流的节点"""
    return state

# 修改工作流图
def create_story_graph(streaming: bool = False, review_queue=None) -> Graph:
    workflow = StateGraph(StoryState)
    
    # 添加节点
    workflow.add_node("generate_story", generate_story)
    workflow.add_node("split_scenes", split_scenes)
    workflow.add_node("generate_images", generate_images)
    workflow.add_node("human_review", lambda x: human_review(x, review_queue))
    workflow.add_node("end", end_workflow)
    
    # 设置工作流程
    workflow.set_entry_point("generate_story")
    workflow.add_edge("generate_story", "human_review")
    
    # 添加条件分支
    workflow.add_conditional_edges(
        "human_review",
        lambda x: "split_scenes" if x.get("approved", False) else "end",
        {
            "split_scenes": "split_scenes",
            "end": "end"
        }
    )
    
    workflow.add_conditional_edges(
        "generate_images",
        lambda x: "end" if x["completed"] else "generate_images",
        {
            "end": "end",
            "generate_images": "generate_images"
        }
    )
    
    workflow.add_edge("split_scenes", "generate_images")
    
    return workflow.compile()

# 修改执行工作流函数
def run_story_workflow(outline: str, streaming: bool = False, review_queue=None) -> Generator[Dict, None, None]:
    if streaming:
        state = StoryState(
            outline=outline,
            story="",
            scenes=[],
            current_scene_index=0,
            completed=False,
            streaming=streaming,
            approved=False  # 初始化审核状态
        )
        
        # 1. 生成故事（流式）
        story_state = None
        for update in generate_story(state):
            if update.get("completed", False):
                story_state = state
                story_state['story'] = update.get("content", "")
            yield update
        
        # 2. 继续执行工作流
        if story_state:
            # 请求人工审核
            yield {
                "type": "review_request",
                "story": story_state["story"],
                "outline": story_state["outline"]
            }
            
            # 等待审核结果
            state = human_review(story_state, review_queue)
            
            if not state["approved"]:
                yield {
                    "type": "review_rejected",
                    "message": "故事内容未通过审核"
                }
                return
            
            # 继续后续流程
            state = split_scenes(state)
            
            while not state['completed']:
                state = generate_images(state)
                yield {
                    "type": "image_update",
                    "scene_index": state['current_scene_index'] - 1,
                    "total_scenes": len(state['scenes']),
                    "completed": state['completed'],
                    "image_url": state['scenes'][state['current_scene_index'] - 1]['image_url'],
                    "scene_text": state['scenes'][state['current_scene_index'] - 1]['text']
                }
            
            yield {
                "type": "final_result",
                "title": state['scenes'][0]['text'].split('，')[0],
                "story": state['story'],
                "scenes": state['scenes'],
                "completed": True
            }
    else:
        # 非流式处理
        graph = create_story_graph(streaming, review_queue)
        initial_state = StoryState(
            outline=outline,
            story="",
            scenes=[],
            current_scene_index=0,
            completed=False,
            streaming=streaming,
            approved=False
        )
        final_state = graph.invoke(initial_state)
        yield {
            "title": final_state["scenes"][0]["text"].split("，")[0],
            "story": final_state["story"],
            "scenes": final_state["scenes"]
        } 