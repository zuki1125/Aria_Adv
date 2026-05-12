# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

latest_message = "（準備中...）"
latest_image = ""
is_thinking = False
latest_comment = ""
latest_status = ""
latest_goal = ""

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/update', methods=['POST'])
def update():
    global latest_message, latest_image, is_thinking
    latest_message = request.json.get('text', latest_message)
    latest_image = request.json.get('image', latest_image)
    is_thinking = request.json.get('thinking', is_thinking)
    return jsonify({"status": "success"})

@app.route('/update_comment', methods=['POST'])
def update_comment():
    global latest_comment
    latest_comment = request.json.get('comment', latest_comment)
    return jsonify({"status": "success"})

@app.route('/update_status', methods=['POST'])
def update_status():
    global latest_status
    latest_status = request.json.get('status', "")
    return jsonify({"status": "success"})

@app.route('/update_goal', methods=['POST'])
def update_goal():
    global latest_goal
    latest_goal = request.json.get('goal', latest_goal)
    return jsonify({"status": "success"})

@app.route('/get_data')
def get_data():
    return jsonify({"text": latest_message, "image": latest_image, "thinking": is_thinking, "comment": latest_comment, "status": latest_status, "goal": latest_goal})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)