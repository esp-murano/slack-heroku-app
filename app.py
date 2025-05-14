# 修正版 app.py（Geminiとの連携込み）
from flask import Flask, request, jsonify
from slack_sdk import WebClient
import os
import google.generativeai as genai

app = Flask(__name__)

# SlackとGeminiのAPIキーを取得
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# SlackとGeminiを設定
slack_client = WebClient(token=SLACK_BOT_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json

    # Slack認証（challengeレスポンス）
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    # Slackのイベントを受け取る
    event = data['event']
    if 'bot_id' in event:
        return jsonify({"status": "ok"})

    text = event.get('text')
    channel = event.get('channel')

    # Geminiで回答を生成
    gemini_response = model.generate_content(text)

    # Slackへ返信
    slack_client.chat_postMessage(
        channel=channel,
        text=gemini_response.text
    )

    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
