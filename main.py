import os
import json
import datetime
import pytz
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, ImageSendMessage
)
import gspread

app = Flask(__name__)

# ====== 從環境變數中取得金鑰 ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_SHEET_NAME = os.environ.get('GOOGLE_SHEET_NAME')

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GOOGLE_SHEET_NAME]):
    print("警告：請確認 LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET 和 GOOGLE_SHEET_NAME 環境變數已設定。")
    # exit() # 部署時建議打開

# ====== Google Sheets API 初始化 ======
try:
    SERVICE_ACCOUNT_FILE = '/etc/secrets/google_credentials.json'
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open(GOOGLE_SHEET_NAME)
    worksheet = sh.sheet1
    print("成功連接 Google Sheet")
except Exception as e:
    print(f"Google Sheet 連接失敗: {e}")
    worksheet = None

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 使用者狀態記錄 ======
user_states = {}
player_counter = 0

# ====================================================================
# ====== ★★★ 修改後的寫入函式 ★★★ ======
# ====================================================================
def record_completion(user_id):
    """
    紀錄玩家通關資訊。
    - 檢查玩家是否已存在。
    - 若不存在，寫入新紀錄並回傳 True。
    - 若已存在，不寫入並回傳 False。
    """
    if not worksheet:
        print("Worksheet 未初始化，無法寫入紀錄。")
        return None

    state = user_states.get(user_id, {})
    if not state or not all(k in state for k in ['name', 'player_id', 'start_time']):
        print(f"使用者 {user_id} 狀態不完整，無法紀錄。")
        return None

    try:
        # 讀取第五欄 (E欄) 的所有 LINE User ID
        existing_ids = worksheet.col_values(5)
        
        # 檢查目前 user_id 是否已存在
        if user_id in existing_ids:
            print(f"使用者 {user_id} 已有紀錄，跳過寫入。")
            return False # 回傳 False 代表是重複遊玩

        # --- 若為新玩家，執行以下寫入動作 ---
        tpe_timezone = pytz.timezone('Asia/Taipei')
        completion_time = datetime.datetime.now(tpe_timezone)
        start_time = state['start_time']
        duration = completion_time - start_time
        duration_seconds = round(duration.total_seconds(), 2)
        completion_time_str = completion_time.strftime("%Y-%m-%d %H:%M:%S")
        player_id = state['player_id']
        name = state['name']
        
        # 新增 LINE User ID 到要寫入的列
        row_to_insert = [player_id, name, completion_time_str, duration_seconds, user_id]
        
        worksheet.insert_row(row_to_insert, 2)
        print(f"成功寫入新紀錄到 Google Sheet: {row_to_insert}")
        return True # 回傳 True 代表是首次通關

    except Exception as e:
        print(f"讀取或寫入 Google Sheet 時發生錯誤: {e}")
        return None


# ====== Webhook 入口 ======
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# ====== 處理文字訊息 ======
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    global player_counter
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    reply_token = event.reply_token

    # ====== 優先處理的通用關鍵字 ======
    if user_message == "週末限定活動報名":
        flex_link_message = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "週末限定活動", "weight": "bold", "size": "xl"},
                    {"type": "text", "text": "名額有限，請點擊下方按鈕立即報名！", "margin": "md", "wrap": True},
                    {"type": "separator", "margin": "xxl"},
                    {
                        "type": "button", "style": "primary", "color": "#905c44", "margin": "xl", "height": "sm",
                        "action": {
                            "type": "uri",
                            "label": "點我前往報名",
                            "uri": "https://docs.google.com/forms/d/e/1FAIpQLSc28lR_7rCNwy7JShQBS9ags6DL0NinKXIUIDJ4dv6YwAIzuA/viewform?usp=dialog"
                        }
                    }
                ]
            }
        }
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="週末限定活動報名連結", contents=flex_link_message))
        return

    elif user_message == "平日常態活動":
        image_url = "https://github.com/chengzi08/tsse-linebot/blob/main/Q2.png?raw=true"
        line_bot_api.reply_message(reply_token, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        return
        
    elif user_message == "活動介紹":
        reply_text = "活動介紹還沒好再等等啦\n" * 8
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text.strip()))
        return

    # ====== 遊戲邏輯 ======
    state = user_states.setdefault(user_id, {'progress': 0})
    progress = state.get('progress', 0)

    if user_message == "開始遊戲" and progress == 0:
        state['progress'] = -1
        line_bot_api.reply_message(reply_token, TextSendMessage(text="歡迎來到問答挑戰！\n請輸入您想在遊戲中使用的名稱："))
        return

    if progress == -1:
        player_name = user_message
        player_counter += 1
        
        state['name'] = player_name
        state['player_id'] = player_counter
        state['start_time'] = datetime.datetime.now(pytz.timezone('Asia/Taipei'))
        state['progress'] = 1
        
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"你好，{player_name}！\n你的挑戰編號是 {player_counter} 號。\n\n遊戲現在開始！祝你好運～"))
        send_question_1(user_id)
        return

    if progress == 1:
        if user_message == "A":
            state['progress'] = 2
            send_question_2(user_id)
        else:
            line_bot_api.push_message(user_id, TextSendMessage(text="答錯囉～再試試看！"))
    elif progress == 2:
        if user_message == "C":
            state['progress'] = 3
            send_question_3(user_id)
        else:
            line_bot_api.push_message(user_id, TextSendMessage(text="錯誤答案！重來看看～"))
    elif progress == 3:
        if user_message == "B":
            state['progress'] = 4
            send_question_4(user_id)
        else:
            line_bot_api.push_message(user_id, TextSendMessage(text="這不是正確答案喔～再試一次！"))
    elif progress == 4:
        if user_message == "B":
            # ★★★ 修改後的通關邏輯 ★★★
            is_first_completion = record_completion(user_id)
            
            if is_first_completion is True:
                # 首次通關
                reply_message_text = "🎉 恭喜你全部答對！你完成了通關～🎊\n您的成績已成功記錄！"
            elif is_first_completion is False:
                # 重複遊玩
                reply_message_text = "感謝您的再次挑戰！我們已保留您首次通關的最佳紀錄。👍"
            else:
                # 紀錄失敗
                reply_message_text = "恭喜通關！不過在記錄成績時發生了一點問題，請聯繫管理員。"
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_message_text))

            # 重置遊戲狀態
            if user_id in user_states:
                del user_states[user_id]
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="最後一題答錯了，再想想看～"))
    
    elif progress == 0:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="請輸入「開始遊戲」來進行挑戰。"))


# ====== 每一題的 Flex Message (內容不變) ======
def send_question_1(user_id):
    flex_message = { "type": "bubble", "hero": {"type": "image", "url": "https://github.com/chengzi08/tsse-linebot/blob/main/Q1.png?raw=true", "size": "full", "aspectRatio": "1.51:1", "aspectMode": "fit"}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第一題：誰是飛天小女警的角色？", "weight": "bold", "size": "md", "margin": "md"}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A 泡泡", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B 豆豆", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C 毛毛", "text": "C"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第一題", contents=flex_message))

def send_question_2(user_id):
    flex_message = { "type": "bubble", "hero": {"type": "image", "url": "https://github.com/chengzi08/tsse-linebot/blob/main/Q2.png?raw=true", "size": "full", "aspectRatio": "1.51:1", "aspectMode": "fit"}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第二題：一次函數 y＝－2x－6 通過哪個點？", "weight": "bold", "size": "md", "margin": "md"}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A (-4, 1)", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B (-4, 2)", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C (-4, -2)", "text": "C"}}, {"type": "button", "style": "primary", "color": "#FFD966", "action": {"type": "message", "label": "D (-4, -1)", "text": "D"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第二題", contents=flex_message))

def send_question_3(user_id):
    flex_message = { "type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第三題：多少個正整數是 18 的倍數，也是 216 的因數？", "weight": "bold", "size": "md", "margin": "md"}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A 2", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B 6", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C 10", "text": "C"}}, {"type": "button", "style": "primary", "color": "#FFD966", "action": {"type": "message", "label": "D 12", "text": "D"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第三題", contents=flex_message))

def send_question_4(user_id):
    flex_message = { "type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第四題：一份套餐比單點雞排+可樂便宜40元，\n單點雞排送一片+兩杯可樂，比兩份套餐便宜10元。\n根據敘述，哪個為正確結論？", "weight": "bold", "size": "md", "margin": "md", "wrap": True}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A 套餐140", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B 套餐120", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C 雞排90", "text": "C"}}, {"type": "button", "style": "primary", "color": "#FFD966", "action": {"type": "message", "label": "D 雞排70", "text": "D"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第四題", contents=flex_message))

# ====== 本地測試/部署啟動 ======
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
