import os
import threading
import requests
import re
import tempfile
from flask import Flask, request, jsonify
from slack_sdk import WebClient
import google.generativeai as genai
import base64

app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

slack_client = WebClient(token=SLACK_BOT_TOKEN)
bot_user_id = slack_client.auth_test()['user_id']

genai.configure(api_key=GEMINI_API_KEY)
model_text = genai.GenerativeModel('gemini-1.5-flash')
model_image = genai.GenerativeModel('gemini-1.5-flash')

headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
processed_event_ids = set()

def clean_text(text):
    return re.sub(r'<@[\w]+>', '', text).strip()

def upload_image_v2(channel, image_bytes, filename='generated_image.png', title='AI生成画像', initial_comment='こちらはAIが生成した画像です。'):
    # Step 1: Slackから外部アップロードURLを取得
    response = slack_client.api_call(
        api_method='files.getUploadURLExternal',
        json={
            "filename": filename,
            "length": len(image_bytes)
        }
    )
    if not response['ok']:
        raise Exception(f"Slackエラー (URL取得失敗): {response['error']}")

    upload_url = response['upload_url']
    file_id = response['file_id']

    # Step 2: 外部URLに画像をアップロード
    upload_response = requests.put(upload_url, data=image_bytes, headers={'Content-Type': 'application/octet-stream'})
    if upload_response.status_code != 200:
        raise Exception(f"外部アップロード失敗 (status code: {upload_response.status_code})")

    # Step 3: ファイルをSlackに投稿
    complete_response = slack_client.api_call(
        api_method='files.completeUploadExternal',
        json={
            "files": [{"id": file_id, "title": title}],
            "channel_id": channel,
            "initial_comment": initial_comment
        }
    )
    if not complete_response['ok']:
        raise Exception(f"Slackエラー (投稿失敗): {complete_response['error']}")

def handle_event(event, event_id):
    if event_id in processed_event_ids:
        return
    processed_event_ids.add(event_id)

    channel = event.get('channel')
    text = clean_text(event.get('text', ''))
    channel_type = event.get('channel_type')

    image_data = None
    mime_type = None

    if 'files' in event:
        for file_info in event['files']:
            if file_info['mimetype'].startswith('image/'):
                image_url = file_info['url_private']

                response = requests.get(image_url, headers=headers)
                if response.status_code != 200:
                    slack_client.chat_postMessage(channel=channel, text="画像の取得に失敗しました。")
                    return

                image_data = response.content
                mime_type = file_info['mimetype']
                break

    if image_data:
        prompt = f"{text}\nこの画像の人物を元に短いストーリーを書いてください。" if text else "この画像の人物を元に短いストーリーを書いてください。"
        try:
            gemini_response = model_text.generate_content([
                prompt,
                {"mime_type": mime_type, "data": image_data}
            ])
            reply_text = gemini_response.text.strip()

            # 画像生成処理
            image_prompt = f"{text}\n画像の人物を元に新しい画像を生成してください。"
            generated_image_response = model_image.generate_content([
                image_prompt,
                {"mime_type": mime_type, "data": image_data}
            ], stream=False)

            if generated_image_response.parts and len(generated_image_response.parts) > 0:
                generated_image_data = generated_image_response.parts[0].inline_data.data
                generated_image_bytes = base64.b64decode(generated_image_data)

                # 新しいSlack API方式でアップロード
                upload_image_v2(
                    channel=channel,
                    image_bytes=generated_image_bytes
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
