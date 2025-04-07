# LangGraph 项目实践总结

## 一、核心概念

### 1. LangGraph 是什么
- 一个基于 LangChain 的工作流引擎
- 支持有向无环图(DAG)方式组织 AI 任务
- 提供状态管理和人工介入机制

### 2. 关键特性
- 节点化任务处理
- 状态管理与传递
- 支持流式输出
- 人工介入机制

## 二、工作流实现方法

### 1. 定义状态
```python
class StoryState(TypedDict):
    outline: str        # 输入参数
    story: str         # 生成的内容
    approved: bool     # 审核状态
    # ... 其他状态
```

### 2. 创建节点
```python
# 1. 定义节点函数
def process_node(state: StoryState) -> StoryState:
    # 处理逻辑
    return state

# 2. 添加到工作流
workflow = StateGraph(StoryState)
workflow.add_node("node_name", process_node)
```

### 3. 设置流程
```python
# 1. 设置入口
workflow.set_entry_point("start_node")

# 2. 添加边
workflow.add_edge("node1", "node2")

# 3. 添加条件分支
workflow.add_conditional_edges(
    "review_node",
    lambda x: "next" if x["approved"] else "end"
)
```

## 三、消息同步机制

### 1. 架构设计
```
前端 <-> Flask服务 <-> LangGraph工作流
   |        |              |
   |        |              |
   +--------+--------------+
        事件流通道
```

### 2. 消息类型
1. 工作流 -> 前端：
```python
yield {
    "type": "status_update",  # 消息类型
    "data": state_data        # 状态数据
}
```

2. 前端 -> 工作流：
```python
# 通过 POST 请求发送
response = await fetch('/api/action', {
    method: 'POST',
    body: JSON.stringify(data)
})
```

### 3. 同步方式
1. **服务端推送(SSE)**
```python
@app.route('/stream')
def stream():
    def generate():
        for state in workflow.run():
            yield f"data: {json.dumps(state)}\n\n"
    return Response(generate(), mimetype='text/event-stream')
```

2. **前端监听**
```javascript
const eventSource = new EventSource('/stream');
eventSource.addEventListener('message', (event) => {
    const data = JSON.parse(event.data);
    // 处理数据
});
```

## 四、人工介入机制

### 1. 核心流程
```
工作流暂停 -> 等待人工处理 -> 接收结果 -> 继续执行
```

### 2. 实现方法

1. **暂停点设置**
```python
def review_node(state: StoryState) -> StoryState:
    # 1. 发送审核请求
    yield {
        "type": "review_request",
        "data": state["content"]
    }
    
    # 2. 等待结果
    result = review_queue.get()  # 阻塞等待
    
    # 3. 更新状态
    state["approved"] = result["approved"]
    return state
```

2. **结果处理**
```python
@app.route('/review', methods=['POST'])
def handle_review():
    result = request.json
    review_queue.put(result)  # 发送结果到队列
    return jsonify({"status": "ok"})
```

### 3. 状态管理
```python
class WorkflowState:
    def __init__(self):
        self.queue = Queue()        # 结果队列
        self.session = None         # 当前会话
        self.status = "running"     # 工作流状态

    def cleanup(self):
        # 清理状态
        self.session = None
        while not self.queue.empty():
            self.queue.get()
```

## 五、最佳实践

### 1. 工作流设计
- 合理拆分节点
- 明确状态定义
- 处理异常情况

### 2. 人工介入
- 设置超时机制
- 保持状态一致
- 清理无用数据

### 3. 消息处理
- 使用类型区分消息
- 确保消息送达
- 处理断连情况

## 六、示例：审核流程

### 1. 完整流程
```
生成内容 -> 请求审核 -> 等待结果 -> 条件处理
```

### 2. 代码实现
```python
# 1. 工作流定义
workflow = StateGraph(StoryState)
workflow.add_node("generate", generate_content)
workflow.add_node("review", human_review)
workflow.add_conditional_edges(
    "review",
    lambda x: "next" if x["approved"] else "end"
)

# 2. 执行流程
def run_workflow():
    try:
        # 初始化状态
        state = initial_state()
        
        # 执行工作流
        for update in workflow.run(state):
            if update["type"] == "review":
                # 发送审核请求
                yield format_sse(update)
                
                # 等待审核结果
                result = wait_for_review()
                state["approved"] = result
                
    finally:
        # 清理状态
        cleanup_state()
```

### 3. 关键点
- 状态管理清晰
- 异常处理完整
- 资源及时清理

## 七、实战经验总结

### 1. 项目构建步骤

1. **环境准备**
```bash
pip install langgraph langchain openai flask python-dotenv
```

2. **项目结构**
```
project/
├── app.py          # Flask应用
├── graph.py        # LangGraph工作流
├── templates/      # 前端页面
└── static/         # 静态资源
```

3. **基础配置**
```python
# .env
OPENAI_API_KEY=你的key
OPENAI_BASE_URL=你的base_url  # 可选
```

### 2. 常见问题与解决方案

1. **工作流中断问题**
- 现象：`Called get_config outside of a runnable context`
- 原因：在非工作流上下文使用 interrupt
- 解决：
```python
# 错误写法
def some_function():
    interrupt({"type": "review"})  # ❌ 直接调用

# 正确写法
def workflow_node(state):
    interrupt({"type": "review"})  # ✅ 在工作流节点中调用
```

2. **状态丢失问题**
- 现象：工作流状态随机丢失
- 原因：多用户并发或会话管理问题
- 解决：
```python
class WorkflowState:
    def __init__(self):
        self.sessions = {}  # 用字典存储多个会话
        
    def get_session(self, session_id):
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "queue": Queue(),
                "status": "running"
            }
        return self.sessions[session_id]
```

3. **前端通信问题**
- 现象：前端无法收到更新
- 原因：SSE连接断开或消息格式错误
- 解决：
```python
# 后端：正确的SSE格式
def generate():
    try:
        for state in workflow.run():
            # 必须包含data前缀和两个换行
            yield f"data: {json.dumps(state)}\n\n"
    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

# 前端：添加重连机制
const connectSSE = () => {
    const es = new EventSource('/stream');
    es.onerror = (e) => {
        es.close();
        setTimeout(connectSSE, 1000);  // 1秒后重连
    };
};
```

### 3. 关键实现点

1. **人工审核流程**
```python
# 1. 工作流节点
def review_node(state):
    # 发送审核请求
    yield {
        "type": "review_request",
        "data": state["content"]
    }
    
    # 等待结果（使用队列避免阻塞）
    try:
        result = queue.get(timeout=300)  # 5分钟超时
        state["approved"] = result["approved"]
    except Empty:
        state["approved"] = False
        state["error"] = "审核超时"
    
    return state

# 2. 前端处理
eventSource.addEventListener('review_request', async (event) => {
    const data = JSON.parse(event.data);
    showReviewDialog(data.content);  // 显示审核界面
});

async function submitReview(approved) {
    try {
        await fetch('/review', {
            method: 'POST',
            body: JSON.stringify({ approved })
        });
        hideReviewDialog();
    } catch (error) {
        showError('审核提交失败');
    }
}
```

2. **流式输出处理**
```python
# 1. 工作流节点
def generate_content(state):
    for chunk in llm.stream("提示词"):
        state["content"] += chunk
        yield {
            "type": "update",
            "content": state["content"]
        }
    return state

# 2. 前端展示
let content = '';
eventSource.addEventListener('update', (event) => {
    const data = JSON.parse(event.data);
    content += data.content;
    updateDisplay(content);  // 更新显示
});
```

### 4. 项目优化要点

1. **性能优化**
- 使用异步队列处理耗时操作
- 实现请求限流和超时控制
- 添加缓存减少重复计算

2. **用户体验**
- 添加加载状态提示
- 实现错误重试机制
- 保存历史记录功能

3. **代码质量**
- 统一错误处理
- 添加日志记录
- 模块化设计

### 5. 注意事项

1. **工作流设计**
- ✅ 每个节点功能单一
- ✅ 状态定义完整清晰
- ❌ 避免节点间耦合

2. **状态管理**
- ✅ 及时清理无用状态
- ✅ 处理并发情况
- ❌ 避免全局状态混乱

3. **错误处理**
- ✅ 捕获所有可能异常
- ✅ 提供友好错误提示
- ❌ 避免静默失败

4. **资源管理**
- ✅ 及时释放资源
- ✅ 控制内存使用
- ❌ 避免资源泄露

### 6. 调试技巧

1. **工作流调试**
```python
# 添加调试日志
def workflow_node(state):
    print(f"节点输入: {state}")  # 输入状态
    result = process(state)
    print(f"节点输出: {result}")  # 输出状态
    return result
```

2. **状态追踪**
```python
class DebugQueue(Queue):
    def put(self, item):
        print(f"队列写入: {item}")
        super().put(item)
    
    def get(self):
        item = super().get()
        print(f"队列读取: {item}")
        return item
```

3. **前端调试**
```javascript
// 监听所有事件
eventSource.onmessage = (event) => {
    console.log('收到消息:', JSON.parse(event.data));
};
```
