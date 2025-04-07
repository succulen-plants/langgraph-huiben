import os
import json
import requests
import time
from typing import List, Dict

class StorybookGenerator:
    def __init__(self):
        self.dashscope_api_key = os.getenv("TONGYI_API_KEY", "sk-a28b2fd89f824e96a7cc1e02cd48b88e")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "sk-RUYMa4nzjcQHBvVmPgYvsYR3A9Nd6OwRgtK1nRqCvFfOUusn")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")
        
    def generate_story(self, outline: str) -> str:
        """使用 ChatGPT 根据大纲生成故事内容"""
        url = f"{self.openai_base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        
        prompt = f"""
        你是一个专业的儿童绘本作家。请根据以下大纲创作一个适合儿童的故事，要求：
        1. 故事生动有趣，富有想象力
        2. 语言简单易懂，适合朗读
        3. 适合3-6岁儿童阅读
        4. 每个场景要有清晰的描写
        5. 故事篇幅适中，分3-4个场景
        6. 每个场景都要有明确的环境描写，便于后续生成配图
        
        大纲：{outline}
        
        请直接返回故事内容，不要加入其他解释。
        """
        
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "你是一个专业的儿童绘本作家，善于创作生动有趣的儿童故事。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            story = response.json()["choices"][0]["message"]["content"].strip()
            return story
        except Exception as e:
            print(f"生成故事时发生错误: {e}")
            # 返回示例故事作为后备方案
            return """小白兔的魔法森林冒险
            
            春天到了，小白兔米莉住在一片神奇的森林里。这天早晨，她发现自己的胡萝卜不见了。
            
            米莉决定去森林里寻找她的胡萝卜。在路上，她遇到了一只友善的小松鼠。
            
            小松鼠告诉米莉，看到一只调皮的小狐狸带着胡萝卜去了森林深处..."""

    def split_into_scenes(self, story: str) -> List[Dict]:
        """将故事分割成场景，并为每个场景生成图片描述"""
        # 使用空行分割场景
        paragraphs = [p.strip() for p in story.split('\n\n') if p.strip()]
        scenes = []
        
        for paragraph in paragraphs:
            # 为每个段落生成场景描述
            scene = {
                "text": paragraph,
                "prompt": f"童话风格的插图，可爱温馨，{paragraph}",
                "negative_prompt": "人物，黑暗，恐怖，写实风格"
            }
            scenes.append(scene)
            
        return scenes

    def generate_image(self, prompt: str, negative_prompt: str) -> str:
        """使用 wanx2.1-t2i-turbo 生成图片"""
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
        
        headers = {
            "X-DashScope-Async": "enable",
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "wanx2.1-t2i-turbo",
            "input": {
                "prompt": prompt,
                "negative_prompt": negative_prompt
            },
            "parameters": {
                "size": "1024*1024",
                "n": 1
            }
        }
        
        response = requests.post(url, headers=headers, json=data)
        task_id = response.json().get("output", {}).get("task_id")
        
        # 轮询检查任务状态
        while True:
            status_response = requests.get(
                f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {self.dashscope_api_key}"}
            )
            result = status_response.json()
            
            if result.get("output", {}).get("task_status") == "SUCCEEDED":
                return result.get("output", {}).get("results", [{}])[0].get("url", "")
            
            time.sleep(2)

    def create_storybook(self, outline: str) -> Dict:
        """生成完整的绘本"""
        # 1. 生成故事
        story = self.generate_story(outline)
        
        # 2. 分割场景
        scenes = self.split_into_scenes(story)
        
        # 3. 为每个场景生成图片
        for scene in scenes:
            image_url = self.generate_image(scene["prompt"], scene["negative_prompt"])
            scene["image_url"] = image_url
        
        # 4. 提取标题（使用第一个场景的第一句话作为标题）
        title = scenes[0]["text"].split("，")[0] if scenes else "我的绘本"
        
        return {
            "title": title,
            "story": story,
            "scenes": scenes
        }

def main():
    # 使用示例
    generator = StorybookGenerator()
    outline = "一只小白兔在魔法森林里寻找丢失的胡萝卜的故事"
    
    print("开始生成绘本...")
    result = generator.create_storybook(outline)
    
    print("\n生成的故事：")
    print(result["story"])
    
    print("\n场景和图片：")
    for i, scene in enumerate(result["scenes"], 1):
        print(f"\n场景 {i}:")
        print(f"文本: {scene['text']}")
        print(f"图片URL: {scene['image_url']}")

if __name__ == "__main__":
    main() 