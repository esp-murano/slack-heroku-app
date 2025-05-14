import os
import threading
import requests
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

headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
processed_events = set()

def handle_event(event):
    channel = event.get('channel')

    # 画像が添付されている場合の処理
    if 'files' in event:
        for file_info in event['files']:
            if file_info['mimetype'].startswith('image/'):
                image_url = file_info['url_private']

                # Slackから画像をダウンロード
                response = requests.get(image_url, headers=headers)
                if response.status_code != 200:
                    slack_client.chat_postMessage(channel=channel, text="画像の取得に失敗しました。")
                    return

                image_data = response.content

                # Geminiで画像認識
                try:
                    gemini_response = model.generate_content(
                        ["画像について説明してください。", {"mime_type": file_info['mimetype'], "data": image_data}]
                    )
                    reply_text = gemini_response.text.strip()
                except Exception as e:
                    reply_text = f"画像認識中にエラーが発生しました: {e}"

                slack_client.chat_postMessage(channel=channel, text=reply_text)
                return

    # 通常のテキストメッセージ処理
    text = event.get('text', '')
    channel_type = event.get('channel_type')

    # BOTへのメンションかDM以外は無視
    if channel_type != 'im' and f"<@{bot_user_id}>" not in text:
        return

    try:
        gemini_response = model.generate_content(text)
        reply_text = gemini_response.text.strip()
        slack_client.chat_postMessage(channel=channel, text=reply_text)
    except Exception as e:
        slack_client.chat_postMessage(channel=channel, text=f"エラーが発生しました: {e}")

@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json

    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get('event', {})
    event_id = data.get('event_id')

    if event_id in processed_events:
        return jsonify({"status": "duplicate event ignored"})
    processed_events.add(event_id)

    # BOT自身または他のBOTメッセージを無視
    if event.get('user') == bot_user_id or 'bot_id' in event:
        return jsonify({"status": "ignored bot message"})

    threading.Thread(target=handle_event, args=(event,)).start()

    return jsonify({"status": "accepted"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
