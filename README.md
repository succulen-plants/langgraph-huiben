# AI绘本生成器

基于LangGraph和OpenAI技术的AI绘本生成器，可以根据用户提供的故事大纲自动生成儿童绘本。

## 功能特点

- 根据故事大纲自动生成适合儿童的故事内容
- 自动为故事生成配图
- 支持实时预览生成过程
- 提供故事审核功能
- 响应式设计，适配各种设备

## 技术栈

- 后端：Python, Flask, LangGraph
- 前端：HTML, CSS, JavaScript
- AI：OpenAI API, 通义API

## 安装步骤

1. 克隆仓库
```bash
git clone https://github.com/yourusername/ai-storybook-generator.git
cd ai-storybook-generator
```

2. 创建并激活虚拟环境
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 配置环境变量
```bash
# 复制示例环境变量文件
cp .env.example .env

# 编辑.env文件，填入您的API密钥
```

## 使用方法

1. 启动应用
```bash
python app.py
```

2. 在浏览器中访问 `http://localhost:5000`

3. 输入故事大纲，点击"开始创作"按钮

4. 等待故事生成，审核故事内容

5. 确认后开始生成图片

## 环境变量说明

- `TONGYI_API_KEY`: 通义API密钥
- `OPENAI_API_KEY`: OpenAI API密钥
- `OPENAI_BASE_URL`: OpenAI API基础URL（可选）
- `DEBUG`: 调试模式（可选）
- `SECRET_KEY`: 应用密钥（可选）

## 注意事项

- 请确保您的API密钥安全，不要将其提交到代码仓库
- 生成图片可能需要一定时间，请耐心等待
- 建议使用现代浏览器以获得最佳体验

## 许可证

MIT 

curl -X POST https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis -H 'X-DashScope-Async: enable' -H "Authorization: Bearer sk-8098a8c255dd4031a4214aecf59db400" -H 'Content-Type: application/json' -d '{"model": "wanx2.1-t2i-turbo", "input": {"prompt": "一间有着精致窗户的花店，漂亮的木质门，摆放着花朵"}, "parameters": {"size": "1024*1024", "n": 1}}'  