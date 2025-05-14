import os
from flask import Flask, request, jsonify
from slack_sdk import WebClient
import google.generativeai as genai

app = Flask(__name__)

# 環境変数からトークンを取得
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# SlackおよびGeminiクライアントを設定
slack_client = WebClient(token=SLACK_BOT_TOKEN)
bot_user_id = slack_client.auth_test()['user_id']
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 重複イベントを防ぐために処理済みイベントを保存
processed_events = set()

@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json

    # Slackの初回認証用チャレンジレスポンス
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get('event', {})
    event_id = data.get('event_id')

    # 重複イベントを無視
    if event_id in processed_events:
        return jsonify({"status": "duplicate event ignored"})
    processed_events.add(event_id)

    # BOT自身または他のBOTのメッセージは無視
    if event.get('user') == bot_user_id or 'bot_id' in event:
        return jsonify({"status": "ignored bot message"})

    text = event.get('text')
    channel = event.get('channel')
    channel_type = event.get('channel_type')

    # BOTへのメンション、またはDMのみ応答
    if channel_type != 'im' and f"<@{bot_user_id}>" not in text:
        return jsonify({"status": "ignored no mention or not DM"})

    try:
        # Geminiで返答を生成
        gemini_response = model.generate_content(text)
        reply_text = gemini_response.text.strip()

        # Slackに返信を送信
        slack_client.chat_postMessage(channel=channel, text=reply_text)

    except Exception as e:
        # エラー発生時の処理（Slackに通知）
        slack_client.chat_postMessage(channel=channel, text=f"エラーが発生しました: {e}")

    # 処理完了レスポンスを返す
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
