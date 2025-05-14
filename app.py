import os
import json
from flask import Flask, request, jsonify
from slack_sdk import WebClient
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))

slack_client = WebClient(token=SLACK_BOT_TOKEN)
bot_user_id = slack_client.auth_test()['user_id']  # 自分のBOTのIDを取得

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

credentials = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO,
    scopes=['https://www.googleapis.com/auth/drive.readonly']
)
drive_service = build('drive', 'v3', credentials=credentials)

@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get('event', {})

    # BOT自身のメッセージは無視する（これがポイント！）
    if event.get('user') == bot_user_id or 'bot_id' in event:
        return jsonify({"status": "ignored bot message"})

    text = event.get('text')
    channel = event.get('channel')

    # メンションがある場合のみ反応する
    if f"<@{bot_user_id}>" not in text:
        return jsonify({"status": "ignored no mention"})

    # Geminiでキーワード抽出
    gemini_response = model.generate_content(
        f"次の文章からGoogle Driveで検索すべきキーワードのみを簡潔に抽出してください：「{text}」"
    )
    keyword = gemini_response.text.strip()

    response = drive_service.files().list(
        q=f"name contains '{keyword}' and mimeType='application/vnd.google-apps.folder'",
        spaces='drive',
        fields='files(id, name)',
        pageSize=3
    ).execute()

    folders = response.get('files', [])
    if folders:
        reply_text = "見つかったフォルダはこちらです：\n"
        for folder in folders:
            reply_text += f"• <https://drive.google.com/drive/folders/{folder['id']}|{folder['name']}>\n"
    else:
        reply_text = "該当するフォルダが見つかりませんでした。"

    slack_client.chat_postMessage(channel=channel, text=reply_text)

    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
