from flask import Flask, render_template, request, Response, stream_with_context, jsonify, session
from graph_generator import run_story_workflow, download_image, IMAGES_DIR
from langgraph.types import Command, interrupt
import json
import os
import threading
from queue import Queue
from datetime import datetime, timedelta
import secrets
import time

app = Flask(__name__)
app.secret_key = 'your-secret-key-replace-in-production'  # 在生产环境中替换为安全的密钥

# 确保存储目录存在
BOOKS_DIR = "static/books"
os.makedirs(BOOKS_DIR, exist_ok=True)

# 存储当前工作流状态
class WorkflowState:
    def __init__(self):
        # 使用字典存储每个会话的状态
        self.sessions = {}
        # 使用字典存储每个会话的审核队列
        self.review_queues = {}
        # 存储会话创建时间
        self.session_times = {}
        
    def create_session(self, session_id):
        """创建新的会话状态"""
        self.sessions[session_id] = None
        self.review_queues[session_id] = Queue()
        self.session_times[session_id] = datetime.now()
        
    def clean_old_sessions(self, max_age_minutes=30):
        """清理超时的会话"""
        now = datetime.now()
        expired = []
        for session_id, time in self.session_times.items():
            if now - time > timedelta(minutes=max_age_minutes):
                expired.append(session_id)
        
        for session_id in expired:
            self.sessions.pop(session_id, None)
            self.review_queues.pop(session_id, None)
            self.session_times.pop(session_id, None)

workflow_state = WorkflowState()

@app.before_request
def before_request():
    """确保每个请求都有会话ID并清理旧会话"""
    if 'session_id' not in session:
        session['session_id'] = secrets.token_urlsafe(16)
    workflow_state.clean_old_sessions()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/view_book/<book_id>')
def view_book(book_id):
    try:
        # 从保存的JSON文件中读取绘本数据
        book_path = os.path.join(BOOKS_DIR, f"book_{book_id}.json")
        with open(book_path, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        return render_template('storybook.html',
                             title=result['title'],
                             story=result['story'],
                             scenes=result['scenes'])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/review', methods=['POST'])
def review_story():
    """处理故事审核结果"""
    try:
        session_id = session.get('session_id')
        if not session_id:
            return jsonify({"error": "No session ID"}), 400
            
        # 如果会话不存在，创建一个新会话
        if session_id not in workflow_state.sessions:
            workflow_state.create_session(session_id)
            print(f"创建新会话: {session_id}")
            
        data = request.json
        approved = data.get('approved', False)
        regenerate = data.get('regenerate', False)
        
        if workflow_state.sessions[session_id] is not None:
            # 将审核结果放入队列
            print(f"接收到审核结果: approved={approved}, regenerate={regenerate}")
            workflow_state.review_queues[session_id].put({"approved": approved, "regenerate": regenerate})
            return jsonify({"status": "success", "approved": approved, "regenerate": regenerate})
        else:
            # 如果工作流会话不存在，创建一个新的工作流会话
            print(f"工作流会话不存在，创建新会话: {session_id}")
            workflow_state.sessions[session_id] = session_id
            workflow_state.review_queues[session_id].put({"approved": approved, "regenerate": regenerate})
            return jsonify({"status": "success", "approved": approved, "new_session": True})
    except Exception as e:
        print(f"Review error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/generate', methods=['GET', 'POST'])
def generate_book():
    # 获取会话ID
    session_id = session.get('session_id')
    if not session_id:
        return "Session error", 400
        
    # 确保会话存在
    if session_id not in workflow_state.sessions:
        workflow_state.create_session(session_id)
        print(f"创建新会话: {session_id}")
    
    # 获取参数
    if request.method == 'GET':
        outline = request.args.get('outline', '')
        streaming = request.args.get('streaming', 'false').lower() == 'true'
    else:
        outline = request.form.get('outline', '')
        streaming = request.form.get('streaming', 'false').lower() == 'true'
    
    if not outline:
        return "请提供故事大纲", 400
    
    if streaming:
        def generate():
            try:
                # 使用会话特定的队列
                review_queue = workflow_state.review_queues[session_id]
                # 清理队列
                while not review_queue.empty():
                    review_queue.get()
                
                # 确保会话状态正确
                workflow_state.sessions[session_id] = session_id
                print(f"开始生成故事，会话ID: {session_id}")
                
                for state in run_story_workflow(outline, streaming=True, review_queue=review_queue):
                    if state.get("type") == "review_request":
                        yield f"event: review_request\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
                        continue
                    
                    if state.get("type") == "review_rejected":
                        yield f"event: review_rejected\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
                        continue
                    
                    if state.get("type") == "final_result":
                        # 使用时间戳和随机数生成唯一的 book_id
                        book_id = f"{int(datetime.now().timestamp())}_{secrets.token_hex(4)}"
                        book_path = os.path.join(BOOKS_DIR, f"book_{book_id}.json")
                        print('=====book_path==',book_path)
                        print('=====state==',state)

                        with open(book_path, 'w', encoding='utf-8') as f:
                            json.dump(state, f, ensure_ascii=False, indent=2)
                        state['book_id'] = book_id
                    
                    yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                print(f"Generate error: {e}")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            finally:
                # 等待一定时间，确保前端有足够时间加载图片
                time.sleep(3)  # 给前端3秒时间加载图片
                
                # 清理会话状态
                workflow_state.sessions[session_id] = None
                while not workflow_state.review_queues[session_id].empty():
                    review_queue.get()
                print(f"故事生成完成，清理会话状态: {session_id}")
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Content-Type': 'text/event-stream',
                'Connection': 'keep-alive'
            }
        )
    else:
        try:
            review_queue = workflow_state.review_queues[session_id]
            result = next(run_story_workflow(outline, streaming=False, review_queue=review_queue))
            
            for scene in result['scenes']:
                if not scene['image_url'].startswith('/static/'):
                    scene['image_url'] = download_image(scene['image_url'], IMAGES_DIR)
            
            # 使用时间戳和随机数生成唯一的 book_id
            book_id = f"{int(datetime.now().timestamp())}_{secrets.token_hex(4)}"
            book_path = os.path.join(BOOKS_DIR, f"book_{book_id}.json")
            with open(book_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            return render_template('storybook.html', 
                                 title=result['title'],
                                 story=result['story'],
                                 scenes=result['scenes'])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0",debug=True) 