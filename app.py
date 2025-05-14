import os
from flask import Flask, request, jsonify
from slack_sdk import WebClient
import google.generativeai as genai

app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

slack_client = WebClient(token=SLACK_BOT_TOKEN)
bot_user_id = slack_client.auth_test()['user_id']

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get('event', {})

    # BOT自身や他のBOTのメッセージは無視
    if event.get('user') == bot_user_id or 'bot_id' in event:
        return jsonify({"status": "ignored bot message"})

    text = event.get('text')
    channel = event.get('channel')
    channel_type = event.get('channel_type')

    # メンションかDM以外は無視
    if channel_type != 'im' and f"<@{bot_user_id}>" not in text:
        return jsonify({"status": "ignored no mention or not DM"})

    # Geminiで生成した返答をSlackに送信
    gemini_response = model.generate_content(text)
    reply_text = gemini_response.text.strip()

    slack_client.chat_postMessage(channel=channel, text=reply_text)

    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
