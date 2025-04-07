from flask import Flask, render_template, request, Response, stream_with_context, jsonify
from graph_generator import run_story_workflow, download_image, IMAGES_DIR
from langgraph.types import Command, interrupt
import json
import os
import threading
from queue import Queue

app = Flask(__name__)

# 确保存储目录存在
BOOKS_DIR = "static/books"
os.makedirs(BOOKS_DIR, exist_ok=True)

# 存储当前工作流状态
class WorkflowState:
    def __init__(self):
        self.review_queue = Queue()
        self.current_session = None

workflow_state = WorkflowState()

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
        data = request.json
        approved = data.get('approved', False)
        
        # 将审核结果放入队列
        if workflow_state.current_session:
            workflow_state.review_queue.put({"approved": approved})
            return jsonify({"status": "success", "approved": approved})
        else:
            return jsonify({"error": "No active workflow session"}), 400
    except Exception as e:
        print(f"Review error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/generate', methods=['GET', 'POST'])
def generate_book():
    global workflow_state
    
    # 获取参数，支持 GET 和 POST
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
                # 清理之前的状态
                while not workflow_state.review_queue.empty():
                    workflow_state.review_queue.get()
                
                # 设置当前会话
                session_id = str(hash(outline))
                workflow_state.current_session = session_id
                
                final_state = None
                for state in run_story_workflow(outline, streaming=True, review_queue=workflow_state.review_queue):
                    print("state=====================", state)
                    
                    if state.get("type") == "review_request":
                        # 发送审核请求事件
                        yield f"event: review_request\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
                        continue
                    
                    if state.get("type") == "review_rejected":
                        # 发送审核拒绝事件
                        yield f"event: review_rejected\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
                        # 不返回，让前端决定是否重新生成
                        continue
                    
                    if state.get("type") == "final_result":
                        final_state = state
                        book_id = session_id
                        book_path = os.path.join(BOOKS_DIR, f"book_{book_id}.json")
                        with open(book_path, 'w', encoding='utf-8') as f:
                            json.dump(state, f, ensure_ascii=False, indent=2)
                        state['book_id'] = book_id
                    
                    yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                
                if final_state:
                    yield f"event: complete\ndata: {json.dumps(final_state, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                print(f"Generate error: {e}")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            finally:
                # 清理会话状态
                workflow_state.current_session = None
                while not workflow_state.review_queue.empty():
                    workflow_state.review_queue.get()
        
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
            result = next(run_story_workflow(outline))
            
            for scene in result['scenes']:
                if not scene['image_url'].startswith('/static/'):
                    scene['image_url'] = download_image(scene['image_url'], IMAGES_DIR)
            
            book_id = str(hash(outline))
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