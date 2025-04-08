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
import re

# 定义状态类型
class StoryState(TypedDict):
    outline: str
    story: str
    scenes: List[Dict]
    current_scene_index: int
    completed: bool
    streaming: bool
    approved: bool  # 审核状态
    regenerate: bool  # 新增重新生成标志
    character_features: str  # 新增人物特征
    character_name: str  # 新增人物名称

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
def generate_story_and_features(state: StoryState) -> Generator[StoryState, None, None]:
    llm = ChatOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        model="gpt-3.5-turbo",
        streaming=True
    )
    
    prompt = f"""
    你是一个专业的儿童绘本创作者。请根据以下大纲同时完成两项任务:
    
    任务1: 创作一个适合儿童的故事，要求：
    - 故事生动有趣，富有想象力
    - 语言简单易懂，适合朗读
    - 适合3-6岁儿童阅读
    - 每个场景要有清晰的描写
    - 故事篇幅适中，200字以内，分3个场景
    - 每个场景都要有明确的环境描写
    
    任务2: 为故事中的主要角色提供详细特征描述，格式如下:
    ---角色特征---
    主要人物：[人物名称]
    - 基础外观：[物种]，[体型]，[年龄特征]
    - 颜色特征：[主体颜色]，[局部颜色]，[花纹特征]
    - 服装配饰：[服装类型]，[配饰细节]，[服装风格]
    - 表情姿态：[表情特征]，[姿态特点]，[动作特征]
    
    大纲：{state['outline']}
    
    请先提供故事内容，然后在故事后面添加角色特征部分。
    """
    
    state['story'] = ""
    collected_content = ""
    
    if state['streaming']:
        for chunk in llm.stream([HumanMessage(content=prompt)]):
            content_chunk = chunk.content
            collected_content += content_chunk
            
            # 分离故事和特征
            parts = collected_content.split('---角色特征---', 1)
            state['story'] = parts[0].strip()
            
            # 提取特征部分(如果已生成)
            if len(parts) > 1:
                state['character_features'] = parts[1].strip()
                # 提取人物名称
                name_match = re.search(r'主要人物：([^\n]+)', state['character_features'])
                if name_match:
                    state['character_name'] = name_match.group(1).strip()
                else:
                    state['character_name'] = "主角"
            
            yield {
                "type": "story_update",
                "content": state['story'],
                "completed": False
            }
        
        # 确保角色特征已提取
        if '---角色特征---' not in collected_content:
            # 如果没有找到分隔符，尝试使用补充调用获取角色特征
            try:
                feature_llm = ChatOpenAI(
                    api_key=os.getenv("OPENAI_API_KEY"),
                    base_url=os.getenv("OPENAI_BASE_URL"),
                    model="gpt-3.5-turbo",
                    streaming=False
                )
                
                feature_prompt = f"""
                基于以下故事内容，提供主要角色的详细特征描述:
                
                故事内容:
                {state['story']}
                
                请按以下格式描述主要角色:
                主要人物：[人物名称]
                - 基础外观：[物种]，[体型]，[年龄特征]
                - 颜色特征：[主体颜色]，[局部颜色]，[花纹特征]
                - 服装配饰：[服装类型]，[配饰细节]，[服装风格]
                - 表情姿态：[表情特征]，[姿态特点]，[动作特征]
                """
                
                feature_response = feature_llm.invoke([HumanMessage(content=feature_prompt)])
                state['character_features'] = feature_response.content.strip()
                
                # 提取人物名称
                name_match = re.search(r'主要人物：([^\n]+)', state['character_features'])
                if name_match:
                    state['character_name'] = name_match.group(1).strip()
                else:
                    state['character_name'] = "主角"
                
                print(f"补充提取的人物特征: {state['character_features']}")
            except Exception as e:
                print(f"补充提取人物特征时出错: {e}")
                state['character_features'] = "主要人物：主角\n- 基础外观：小动物，可爱，幼年\n- 颜色特征：彩色\n- 服装配饰：简单服装\n- 表情姿态：微笑，活泼"
                state['character_name'] = "主角"
        
        # 最后一次更新，标记完成
        yield {
            "type": "story_update",
            "content": state['story'],
            "completed": True
        }
    else:
        response = llm.invoke([HumanMessage(content=prompt)])
        collected_content = response.content
        
        # 分离故事和特征
        parts = collected_content.split('---角色特征---', 1)
        state['story'] = parts[0].strip()
        
        # 提取特征部分(如果已生成)
        if len(parts) > 1:
            state['character_features'] = parts[1].strip()
            # 提取人物名称
            name_match = re.search(r'主要人物：([^\n]+)', state['character_features'])
            if name_match:
                state['character_name'] = name_match.group(1).strip()
            else:
                state['character_name'] = "主角"
        else:
            # 如果没有找到分隔符，设置默认特征
            state['character_features'] = "主要人物：主角\n- 基础外观：小动物，可爱，幼年\n- 颜色特征：彩色\n- 服装配饰：简单服装\n- 表情姿态：微笑，活泼"
            state['character_name'] = "主角"
            
        yield state

# 场景分割节点
def split_scenes(state: StoryState) -> StoryState:
    # 清理现有场景列表，确保重新生成时不会累加
    state['scenes'] = []
    
    # 使用单次LLM调用，同时进行场景分割与角色/特征分析
    llm = ChatOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        model="gpt-3.5-turbo",
        streaming=False
    )
    
    # 获取已存在的角色特征
    character_features = state.get('character_features', '')
    character_name = state.get('character_name', '主角')
    
    # 构建更高效的提示词，同时完成多个任务
    prompt = f"""
    分析以下儿童故事，并完成这些任务:
    1. 将故事分成3个关键场景（如果场景不足3个，请合理划分）
    2. 为每个场景提取关键角色
    3. 为每个场景生成详细的图像提示词，确保包含角色特征
    4：使用中文描述
    
    按以下JSON格式返回结果:
    ```json
    {{
        "scenes": [
            {{
                "text": "场景1内容",
                "characters": ["角色1", "角色2"],
                "image_prompt": "详细的图像描述...",
                "character_features": "角色1: ...\n角色2: ..."
            }},
            // 场景2、场景3...
        ]
    }}
    ```
    
    故事内容:
    {state['story']}
    
    已知的角色特征:
    {character_features}
    
    图像提示词要求:
    - 风格要求：必须使用3D风格，童话风格，可爱温馨
    - 包含场景中的主要角色及其动作
    - 描述环境、氛围和关键元素
    - 提示词应该足够详细，便于图像生成
    - 使用英文描述
    - 确保在提示词中包含角色的外观特征，如颜色、服装、表情等
    - 每个提示词必须以"3D style, fairy tale style, cute and warm"开头
    """
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        
        # 提取JSON部分
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析整个内容
            json_str = content
            
        import json
        result = json.loads(json_str)
        
        # 更新场景列表
        for scene_data in result.get("scenes", []):
            # 获取场景中的角色特征
            scene_character_features = scene_data.get("character_features", "")
            
            # 如果没有场景特定的角色特征，使用全局角色特征
            if not scene_character_features:
                scene_character_features = character_features
            
            # 获取图像提示词
            image_prompt = scene_data.get("image_prompt", "")
            
            # 确保提示词包含风格要求
            if not image_prompt.startswith("3D style"):
                image_prompt = f"3D style, fairy tale style, cute and warm, {image_prompt}"
            
            # 创建场景对象，包含角色特征
            scene = {
                "text": scene_data.get("text", ""),
                "prompt": image_prompt,
                "negative_prompt": "人物，黑暗，恐怖，写实风格，与主要人物特征不符的任何形象，低质量，模糊，变形",
                "character_features": scene_character_features  # 添加角色特征到场景中
            }
            state['scenes'].append(scene)
        
        print(f"一次性分析完成，共 {len(state['scenes'])} 个场景")
        print(f"场景列表: {state['scenes']}")
            
    except Exception as e:
        print(f"场景分析出错: {e}")
        # 出错时使用简单的段落分割作为备选方案
        paragraphs = [p.strip() for p in state['story'].split('\n\n') if p.strip()]
        
        # 确保至少有一个场景
        if not paragraphs:
            paragraphs = [state['story']]
            
        for paragraph in paragraphs:
            scene = {
                "text": paragraph,
                "prompt": f"3D style, fairy tale style, cute and warm, {paragraph}",
                "negative_prompt": "人物，黑暗，恐怖，写实风格，低质量，模糊，变形",
                "character_features": character_features  # 添加全局角色特征
            }
            state['scenes'].append(scene)
            
        print(f"备选方案：分割场景完成，共 {len(state['scenes'])} 个场景")
    
    # 重置场景索引和完成状态
    state['current_scene_index'] = 0
    state['completed'] = False
    
    return state

# 图片生成节点
def generate_images(state: StoryState) -> StoryState:
    from storybook_generator import StorybookGenerator
    generator = StorybookGenerator()
    
    # 检查索引是否有效
    if state['current_scene_index'] >= len(state['scenes']):
        print(f"警告: 场景索引 {state['current_scene_index']} 超出范围，共 {len(state['scenes'])} 个场景")
        state['completed'] = True
        return state
    
    scene = state['scenes'][state['current_scene_index']]
    print(f"生成第 {state['current_scene_index'] + 1}/{len(state['scenes'])} 张图片")
    
    # 直接使用预先生成的提示词
    image_url = generator.generate_image(scene['prompt'], scene['negative_prompt'])
    
    # 下载并保存图片
    local_image_path = download_image(image_url, IMAGES_DIR)
    scene['image_url'] = local_image_path  # 使用本地路径替换远程URL
    
    # 更新索引
    state['current_scene_index'] += 1
    
    # 检查是否完成所有场景
    if state['current_scene_index'] >= len(state['scenes']):
        print("所有场景图片已生成完成")
        state['completed'] = True
    else:
        print(f"下一个场景索引: {state['current_scene_index']}")
        state['completed'] = False
    
    return state

# 添加人工审核工具
def human_review(state: StoryState, review_queue=None) -> StoryState:
    """请求人工审核故事内容"""
    print(f"\n[System] 请求人工审核故事内容")
    try:
        if review_queue is None:
            print("No review queue provided")
            state["approved"] = False
            state["regenerate"] = False
            return state
            
        # 等待审核结果
        review_data = review_queue.get()  # 从队列中获取审核结果
        print(f"Received review data: {review_data}")
        
        if isinstance(review_data, dict):
            state["approved"] = review_data.get("approved", False)
            state["regenerate"] = review_data.get("regenerate", False)  # 获取重新生成标志
            print(f"Regenerate flag: {state['regenerate']}")
        else:
            print(f"Unexpected review data type: {type(review_data)}")
            state["approved"] = False
            state["regenerate"] = False
            
    except Exception as e:
        print(f"Error in human review: {e}")
        state["approved"] = False
        state["regenerate"] = False
    
    print(f"Review result: {'Approved' if state['approved'] else 'Rejected'}, Regenerate: {state['regenerate']}")
    return state

# 添加结束节点
def end_workflow(state: StoryState) -> StoryState:
    """结束工作流的节点"""
    return state

# 修改工作流图
def create_story_graph(streaming: bool = False, review_queue=None) -> Graph:
    workflow = StateGraph(StoryState)
    
    # 添加节点
    workflow.add_node("generate_story", generate_story_and_features)
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
        lambda x: "split_scenes" if x.get("approved", False) 
                 else "generate_story" if x.get("regenerate", False) 
                 else "end",
        {
            "split_scenes": "split_scenes",
            "generate_story": "generate_story",
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
            approved=False,
            regenerate=False,
            character_features="",
            character_name=""
        )
        
        # 1. 生成故事与特征（流式）
        story_state = None
        for update in generate_story_and_features(state):
            if update.get("completed", False):
                story_state = state
                story_state['story'] = update.get("content", "")
            yield update
        
        # 2. 提取人物特征已在故事生成步骤完成
        if story_state:
            # 发送角色特征通知
            yield {
                "type": "character_features",
                "features": story_state.get("character_features", ""),
                "name": story_state.get("character_name", "主角")
            }
            
            # 请求人工审核
            yield {
                "type": "review_request",
                "story": story_state["story"],
                "outline": story_state["outline"],
                "character_features": story_state.get("character_features", ""),
                "character_name": story_state.get("character_name", "主角")
            }
            
            # 等待审核结果
            state = human_review(story_state, review_queue)
            print(f"审核结果: approved={state['approved']}, regenerate={state.get('regenerate', False)}")
            
            if not state["approved"]:
                if state.get("regenerate", False):
                    # 如果需要重新生成，重置状态并继续执行
                    print(f"检测到重新生成标志，开始重新生成故事")
                    yield {
                        "type": "regenerate_story",
                        "message": "重新生成故事"
                    }
                    # 重新生成故事
                    state = StoryState(
                        outline=outline,
                        story="",
                        scenes=[],
                        current_scene_index=0,
                        completed=False,
                        streaming=streaming,
                        approved=False,
                        regenerate=False,
                        character_features="",
                        character_name=""
                    )
                    # 重新启动故事生成流程
                    print(f"重置状态，准备生成新故事")
                    for update in generate_story_and_features(state):
                        if update.get("completed", False):
                            story_state = state
                            story_state['story'] = update.get("content", "")
                        yield update
                    
                    # 发送角色特征通知
                    yield {
                        "type": "character_features",
                        "features": story_state.get("character_features", ""),
                        "name": story_state.get("character_name", "主角")
                    }
                        
                    # 继续请求审核
                    print(f"新故事生成完成，请求新一轮审核")
                    yield {
                        "type": "review_request",
                        "story": story_state["story"],
                        "outline": story_state["outline"],
                        "character_features": story_state.get("character_features", ""),
                        "character_name": story_state.get("character_name", "主角")
                    }
                    
                    # 等待新的审核结果
                    state = human_review(story_state, review_queue)
                    print(f"新审核结果: approved={state['approved']}, regenerate={state.get('regenerate', False)}")
                    
                    if not state["approved"]:
                        print(f"新故事仍被拒绝，结束流程")
                        yield {
                            "type": "review_rejected",
                            "message": "新故事内容未通过审核"
                        }
                        return
                else:
                    # 正常的拒绝处理
                    print(f"故事被拒绝，无重新生成标志，结束流程")
                    yield {
                        "type": "review_rejected",
                        "message": "故事内容未通过审核"
                    }
                    return
            
            # 继续后续流程
            print(f"故事通过审核，继续处理")
            state = split_scenes(state)
            print(f"分场景后的状态: {len(state['scenes'])} 个场景, 当前索引: {state['current_scene_index']}")
            
            # 图片生成循环
            scene_count = len(state['scenes'])
            processed_scene_count = 0
            
            while processed_scene_count < scene_count:
                # 确保索引在有效范围内
                if state['current_scene_index'] >= scene_count:
                    print(f"警告: 索引 {state['current_scene_index']} 超出范围")
                    break
                
                # 生成当前场景的图片
                print(f"处理场景 {state['current_scene_index']+1}/{scene_count}")
                state = generate_images(state)
                processed_scene_count += 1
                
                # 发送更新信息
                yield {
                    "type": "image_update",
                    "scene_index": state['current_scene_index'] - 1,
                    "total_scenes": scene_count,
                    "completed": processed_scene_count >= scene_count,
                    "image_url": state['scenes'][state['current_scene_index'] - 1]['image_url'],
                    "scene_text": state['scenes'][state['current_scene_index'] - 1]['text']
                }
                
                # 调试信息
                print(f"场景 {state['current_scene_index']}/{scene_count} 处理完成, 已处理 {processed_scene_count}/{scene_count}")
            
            # 确保完成状态正确设置
            state['completed'] = True
            
            # 返回最终结果
            if len(state['scenes']) > 0:
                title = state['scenes'][0]['text'].split('，')[0] if '，' in state['scenes'][0]['text'] else state['scenes'][0]['text'][:10]
                yield {
                    "type": "final_result",
                    "title": title,
                    "story": state['story'],
                    "scenes": state['scenes'],
                    "completed": True
                }
            else:
                print("警告: 没有场景数据")
                yield {
                    "type": "final_result",
                    "title": "故事",
                    "story": state['story'],
                    "scenes": [],
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
            approved=False,
            regenerate=False,
            character_features="",
            character_name=""
        )
        final_state = graph.invoke(initial_state)
        
        # 确保有场景数据
        if final_state["scenes"]:
            title = final_state["scenes"][0]["text"].split("，")[0] if "，" in final_state["scenes"][0]["text"] else final_state["scenes"][0]["text"][:10]
            yield {
                "title": title,
                "story": final_state["story"],
                "scenes": final_state["scenes"]
            }
        else:
            yield {
                "title": "故事",
                "story": final_state["story"],
                "scenes": []
            } 

def generate_scene_image(scene_text: str, characters: List[str], features: str) -> str:
    """生成场景图片"""
    llm = ChatOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
        model="gpt-3.5-turbo",
        streaming=False
    )
    
    prompt = f"""
    请根据以下场景描述和角色特征，生成一个详细的图片生成提示词。
    提示词应该包含场景的环境描述、角色外观、表情和动作，以及整体氛围。
    使用英文描述，每个元素用逗号分隔。
    
    场景描述:
    {scene_text}
    
    角色:
    {', '.join(characters)}
    
    角色特征:
    {features}
    """
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        image_prompt = response.content.strip()
        
        print(f"生成的图片提示词: {image_prompt}")
        
        # 调用实际的图片生成服务
        from storybook_generator import StorybookGenerator
        generator = StorybookGenerator()
        
        # 调用图像生成API
        negative_prompt = "低质量, 模糊, 变形, 不相关内容"
        image_url = generator.generate_image(image_prompt, negative_prompt)
        
        # 下载并保存图片
        local_image_path = download_image(image_url, IMAGES_DIR)
        return local_image_path
    except Exception as e:
        print(f"图片生成出错: {e}")
        # 出错时返回一个默认图片 URL
        return "/static/images/error_image.png" 