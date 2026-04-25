#!/usr/bin/env python3
"""
简单待办事项管理器
功能：添加、完成、删除、查看待办
"""

import json
import os
import sys
from datetime import datetime

TODO_FILE = "todos.json"

def load_todos():
    """加载待办事项"""
    if os.path.exists(TODO_FILE):
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_todos(todos):
    """保存待办事项"""
    with open(TODO_FILE, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

def add_todo(todos, task):
    """添加待办"""
    todo = {
        "id": len(todos) + 1,
        "task": task,
        "completed": False,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    todos.append(todo)
    return todos

def complete_todo(todos, todo_id):
    """完成待办"""
    for todo in todos:
        if todo["id"] == todo_id:
            todo["completed"] = True
            return True
    return False

def delete_todo(todos, todo_id):
    """删除待办"""
    todos = [t for t in todos if t["id"] != todo_id]
    # 重新编号
    for i, todo in enumerate(todos, 1):
        todo["id"] = i
    return todos

def show_todos(todos):
    """显示待办列表"""
    if not todos:
        print("\n📝 暂无待办事项\n")
        return
    
    print("\n" + "="*50)
    print("📋 待办事项")
    print("="*50)
    
    pending = [t for t in todos if not t["completed"]]
    completed = [t for t in todos if t["completed"]]
    
    if pending:
        print("\n🔲 未完成:")
        for todo in pending:
            print(f"  [{todo['id']}] {todo['task']}")
    
    if completed:
        print("\n✅ 已完成:")
        for todo in completed:
            print(f"  [{todo['id']}] {todo['task']} ✓")
    
    print("\n" + "="*50)
    print(f"总计: {len(todos)} | 未完成: {len(pending)} | 已完成: {len(completed)}")
    print("="*50 + "\n")

def show_help():
    """显示帮助"""
    print("""
📌 使用方法:
  python todo.py add <任务>     - 添加新待办
  python todo.py done <编号>   - 标记为完成
  python todo.py del <编号>     - 删除待办
  python todo.py list          - 显示全部
  python todo.py clear         - 清空已完成

📌 示例:
  python todo.py add 买牛奶
  python todo.py add 学习Python
  python todo.py done 1
  python todo.py list
""")

def main():
    todos = load_todos()
    
    if len(sys.argv) < 2:
        show_todos(todos)
        show_help()
        return
    
    action = sys.argv[1].lower()
    
    if action == "add" and len(sys.argv) > 2:
        task = " ".join(sys.argv[2:])
        todos = add_todo(todos, task)
        save_todos(todos)
        print(f"✅ 已添加: {task}")
    
    elif action == "done":
        todo_id = int(sys.argv[2])
        if complete_todo(todos, todo_id):
            save_todos(todos)
            print(f"✅ 任务 {todo_id} 已完成!")
        else:
            print(f"❌ 找不到任务 {todo_id}")
    
    elif action == "del":
        todo_id = int(sys.argv[2])
        todos = delete_todo(todos, todo_id)
        save_todos(todos)
        print(f"🗑️ 任务 {todo_id} 已删除")
    
    elif action == "list":
        show_todos(todos)
    
    elif action == "clear":
        todos = [t for t in todos if not t["completed"]]
        save_todos(todos)
        print("🧹 已清空所有已完成任务")
    
    elif action in ["help", "-h", "--help"]:
        show_help()
    
    else:
        print(f"❓ 未知命令: {action}")
        show_help()

if __name__ == "__main__":
    main()