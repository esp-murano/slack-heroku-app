import os
import threading
import requests
import re
import base64
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import google.generativeai as genai

app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

slack_client = WebClient(token=SLACK_BOT_TOKEN)
bot_user_id = slack_client.auth_test()['user_id']

genai.configure(api_key=GEMINI_API_KEY)
model_text = genai.GenerativeModel('gemini-2.0-flash')

headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
processed_event_ids = set()
processed_messages = set()

def clean_text(text):
    return re.sub(r'<@[\w]+>', '', text).strip()

def generate_image_by_gemini(prompt):
    API_KEY = GEMINI_API_KEY
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-preview-image-generation:generateContent?key={API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
    }
    res = requests.post(url, headers=headers, json=data)
    res_json = res.json()
    if "candidates" not in res_json:
        return None, "Gemini API画像生成に失敗しました"
    base64_img = res_json["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    return base64_img, None

def upload_image_to_slack(channel, image_bytes, filename="generated_image.png", initial_comment="AIが生成した画像です"):
    try:
        if not isinstance(image_bytes, bytes) or len(image_bytes) == 0:
            slack_client.chat_postMessage(channel=channel, text="生成画像データが不正です。")
            return
        slack_client.files_upload_v2(
            channel=channel,
            file=image_bytes,
            filename=filename,
            initial_comment=initial_comment
        )
    except SlackApiError as e:
        slack_client.chat_postMessage(channel=channel, text=f"Slackアップロードエラー: {e.response['error']}")

def handle_event(event, event_id):
    if event_id in processed_event_ids:
        return
    processed_event_ids.add(event_id)

    msg_ts = event.get('ts')
    if msg_ts in processed_messages:
        return
    processed_messages.add(msg_ts)

    channel = event.get('channel')
    text = clean_text(event.get('text', ''))
    channel_type = event.get('channel_type')

    image_data = None
    mime_type = None
    has_image = False

    if 'files' in event:
        for file_info in event['files']:
            if file_info['mimetype'].startswith('image/'):
                has_image = True
                image_url = file_info['url_private']
                response = requests.get(image_url, headers=headers)
                if response.status_code != 200:
                    slack_client.chat_postMessage(channel=channel, text="画像の取得に失敗しました。")
                    return
                image_data = response.content
                mime_type = file_info['mimetype']
                break

    if has_image and event.get('type') == 'app_mention':
        return

    if image_data:
        prompt = f"{text}\nこの画像を元に短いストーリーを書いてください。" if text else "この画像を元に短いストーリーを書いてください。"
        try:
            # ストーリー生成（テキスト）
            gemini_response = model_text.generate_content([
                prompt,
                {"mime_type": mime_type, "data": image_data}
            ])
            reply_text = gemini_response.text.strip()

            # 画像生成（Geminiプレビュー画像生成API利用）
            image_prompt = f"{text}\nこの画像を元に新しい画像を生成してください。"
            base64_img, error = generate_image_by_gemini(image_prompt)
            if error:
                slack_client.chat_postMessage(channel=channel, text=error)
            else:
                # base64画像が空の場合もエラー
                if not base64_img or not base64_img.strip():
                    slack_client.chat_postMessage(channel=channel, text="AI生成画像のデータが空です。")
                    return
                # プレフィックス対応
                if base64_img.startswith("data:"):
                    base64_img_data = base64_img.split(",")[-1]
                else:
                    base64_img_data = base64_img
                try:
                    generated_image_bytes = base64.b64decode(base64_img_data)
                except Exception as e:
                    slack_client.chat_postMessage(channel=channel, text=f"base64 decode失敗: {e}")
                    return

                upload_image_to_slack(
                    channel=channel,
                    image_bytes=generated_image_bytes,
                    filename='generated_image.png',
                    initial_comment="こちらはAIが生成した画像です。"
                )

        except Exception as e:
            reply_text = f"エラーが発生しました: {e}"

        slack_client.chat_postMessage(channel=channel, text=reply_text)

    elif channel_type == 'im' or text:
        try:
            gemini_response = model_text.generate_content(text)
            reply_text = gemini_response.text.strip()
        except Exception as e:
            reply_text = f"エラーが発生しました: {e}"

        slack_client.chat_postMessage(channel=channel, text=reply_text)

@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json

    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get('event', {})
    event_id = data.get('event_id')

    if event.get('user') == bot_user_id or 'bot_id' in event:
        return jsonify({"status": "ignored bot message"})

    threading.Thread(target=handle_event, args=(event, event_id)).start()

    return jsonify({"status": "accepted"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
