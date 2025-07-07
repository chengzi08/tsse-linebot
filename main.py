import os
import pytz
import datetime
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, ImageMessage, ImageSendMessage
)

import gspread
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

app = Flask(__name__)

# ====== 環境變數與 API 初始化 ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_SHEET_NAME = os.environ.get('GOOGLE_SHEET_NAME')
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')

SERVICE_ACCOUNT_FILE = '/etc/secrets/google_credentials.json'

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GOOGLE_SHEET_NAME, GOOGLE_DRIVE_FOLDER_ID]):
    print("警告：請確認所有環境變數 (LINE..., GOOGLE_SHEET_NAME, GOOGLE_DRIVE_FOLDER_ID) 已設定。")

# --- Google Sheets 和 Drive 初始化 (最終修正版) ---
try:
    # 1. gspread 獨立認證，這部分已知是成功的
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open(GOOGLE_SHEET_NAME)
    worksheet = sh.sheet1
    print("成功連接 Google Sheet")
except Exception as e:
    worksheet = None
    print(f"Google Sheet 連接失敗: {e}")

try:
    # 2. PyDrive2 也使用同一個金鑰檔案進行獨立認證
    gauth = GoogleAuth()
    # ★ 關鍵修改：直接呼叫 ServiceAuth()，它會自動讀取 settings.yaml 或 client_secrets.json
    # 但在 Render 環境中，我們需要更明確的指定
    gauth.ServiceAuth(SERVICE_ACCOUNT_FILE)
    drive = GoogleDrive(gauth)
    print("成功初始化 Google Drive Client")
except Exception as e:
    drive = None
    print(f"Google Drive Client 初始化失敗: {e}")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 使用者狀態記錄 ======
user_states = {}

# ====== 核心函式：取得玩家資訊 ======
def get_player_info(user_id):
    global worksheet # ★★★ 關鍵修改 ★★★
    if not worksheet: return None
    try:
        cells = worksheet.findall(user_id, in_column=5)
        if not cells:
            all_player_ids = worksheet.col_values(9)[1:]
            all_player_ids_int = [int(i) for i in all_player_ids if i and i.isdigit()]
            new_id = max(all_player_ids_int) + 1 if all_player_ids_int else 1
            return {'id': new_id, 'play_count': 1, 'is_new': True}
        else:
            first_cell = cells[0]
            permanent_id_str = worksheet.cell(first_cell.row, 9).value
            permanent_id = int(permanent_id_str) if permanent_id_str and permanent_id_str.isdigit() else 0
            all_play_counts = [int(worksheet.cell(c.row, 10).value) for c in cells if worksheet.cell(c.row, 10).value.isdigit()]
            next_play_count = max(all_play_counts) + 1 if all_play_counts else 1
            return {'id': permanent_id, 'play_count': next_play_count, 'is_new': False}
    except Exception as e:
        print(f"獲取玩家資訊時出錯: {e}")
        return None

# ====== 核心函式：寫入紀錄 ======
def record_completion(user_id, image_url=None):
    global worksheet # ★★★ 關鍵修改 ★★★
    if not worksheet: return None
    state = user_states.get(user_id, {})
    if 'player_info' not in state: return None
    player_info = state['player_info']
    is_first_ever_completion = player_info['is_new']
    try:
        tpe_timezone = pytz.timezone('Asia/Taipei')
        completion_time = datetime.datetime.now(tpe_timezone)
        duration_seconds = round((completion_time - state['start_time']).total_seconds(), 2)
        row_to_insert = [f"{player_info['id']}-{player_info['play_count']}", state['name'], completion_time.strftime("%Y-%m-%d %H:%M:%S"), duration_seconds, user_id, image_url or "", "否", "是" if is_first_ever_completion else "否", player_info['id'], player_info['play_count']]
        worksheet.insert_row(row_to_insert, 2)
        return {'is_first': is_first_ever_completion, 'count': player_info['play_count']}
    except Exception as e:
        print(f"寫入 Google Sheet 時發生錯誤: {e}")
        return None

# ====== 核心函式：兌換獎品 ======
def redeem_prize(user_id):
    global worksheet # ★★★ 關鍵修改 ★★★
    if not worksheet: return None
    try:
        cell = worksheet.find(user_id, in_column=5)
        if not cell:
            return 'not_found'
        
        if worksheet.acell(f'G{cell.row}').value == '是':
            return 'already_redeemed'
        
        worksheet.update_acell(f'G{cell.row}', '是')
        return 'success'
    except Exception as e:
        print(f"兌獎時發生錯誤: {e}")
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
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    reply_token = event.reply_token

    if user_message == "開始遊戲":
        if user_id in user_states:
            del user_states[user_id]
        user_states[user_id] = {'progress': 0}
        send_start_menu(reply_token)
        return

    elif user_message == "週末限定活動報名":
        flex_link_message = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "週末限定活動", "weight": "bold", "size": "xl"}, {"type": "text", "text": "名額有限，請點擊下方按鈕立即報名！", "margin": "md", "wrap": True}, {"type": "separator", "margin": "xxl"}, {"type": "button", "style": "primary", "color": "#905c44", "margin": "xl", "height": "sm", "action": {"type": "uri", "label": "點我前往報名", "uri": "https://docs.google.com/forms/d/e/1FAIpQLSc28lR_7rCNwy7JShQBS9ags6DL0NinKXIUIDJ4dv6YwAIzuA/viewform?usp=dialog"}}]}}
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
    
    state = user_states.get(user_id)
    if not state:
        return
        
    progress = state.get('progress', 0)
    
    if user_message == "進入遊戲" and progress == 0:
        state['progress'] = -1
        line_bot_api.reply_message(reply_token, TextSendMessage(text="歡迎來到問答挑戰！\n請輸入您想在遊戲中使用的名稱："))
        return

    if user_message == "兌換獎項" and progress == 0:
        state['progress'] = -2
        line_bot_api.reply_message(reply_token, TextSendMessage(text="請輸入兌換碼："))
        return

    if progress == -2:
        if user_message == "PASS":
            result = redeem_prize(user_id)
            reply_text = {'success': "獎項兌換成功！", 'already_redeemed': "您已兌換過獎品囉！", 'not_found': "您尚未完成遊戲挑戰，無法兌換獎品喔！"}.get(result, "兌換時發生錯誤，請聯繫管理員。")
            state['progress'] = 0
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="兌換碼錯誤，請重新輸入。"))
        return
        
    if progress == -1:
        player_name = user_message
        player_info = get_player_info(user_id)
        if not player_info:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="抱歉，無法讀取玩家資料，請稍後再試。"))
            return

        state.update({'name': player_name, 'player_info': player_info, 'start_time': datetime.datetime.now(pytz.timezone('Asia/Taipei')), 'progress': 1})
        reply_text = f"你好，{player_name}！\n你的挑戰編號是 {player_info['id']}-{player_info['play_count']} 號。\n\n遊戲現在開始！"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        send_question_1(user_id)
        return

    if progress == 1:
        if user_message == "A": state['progress'] = 2; send_question_2(user_id)
        else: line_bot_api.push_message(user_id, TextSendMessage(text="答錯囉～再試試看！"))
    elif progress == 2:
        if user_message == "C": state['progress'] = 3; send_question_3(user_id)
        else: line_bot_api.push_message(user_id, TextSendMessage(text="錯誤答案！重來看看～"))
    elif progress == 3:
        if user_message == "B": state['progress'] = 4; send_question_4(user_id)
        else: line_bot_api.push_message(user_id, TextSendMessage(text="這不是正確答案喔～再試一次！"))
    elif progress == 4:
        if user_message == "B": state['progress'] = 5; send_question_5(user_id)
        else: line_bot_api.reply_message(reply_token, TextSendMessage(text="最後一題答錯了，再想想看～"))

# ====== 處理圖片訊息 ======
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    state = user_states.get(user_id, {})
    if state.get('progress') != 5: return

    if not drive:
        line_bot_api.push_message(user_id, TextSendMessage(text="抱歉，圖片上傳服務暫時無法使用。"))
        return

    temp_file_path = f"{event.message.id}.jpg"
    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="收到照片，正在上傳至雲端...✨"))
        
        message_content = line_bot_api.get_message_content(event.message.id)
        with open(temp_file_path, 'wb') as fd:
            for chunk in message_content.iter_content():
                fd.write(chunk)

        drive_file = drive.CreateFile({'title': f'{user_id}-{event.message.id}.jpg', 'parents': [{'id': GOOGLE_DRIVE_FOLDER_ID}]})
        drive_file.SetContentFile(temp_file_path)
        drive_file.Upload()
        drive_file.InsertPermission({'type': 'anyone', 'value': 'anyone', 'role': 'reader'})
        image_url = drive_file['webViewLink']

        record_result = record_completion(user_id, image_url=image_url)
        if record_result:
            redemption_info = (
                "\n\n"
                "您的兌換碼為【PASS】。\n"
                "（請將此畫面出示給關主，由關主為您操作兌換，請勿自行輸入）"
            )
            if record_result['is_first']:
                final_message = "🎉 照片上傳成功，恭喜你完成所有挑戰！🎊\n您的成績已成功記錄！" + redemption_info
            else:
                final_message = f"🎉 挑戰成功！這是您的第 {record_result['count']} 次通關紀錄！" + redemption_info
        else:
            final_message = "恭喜通關！但在記錄成績時發生錯誤，請聯繫管理員。"
        
        line_bot_api.push_message(user_id, TextSendMessage(text=final_message))

    except Exception as e:
        print(f"圖片處理失敗: {e}")
        line_bot_api.push_message(user_id, TextSendMessage(text="啊！照片上傳失敗了...請再試一次。"))
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if user_id in user_states:
            del user_states[user_id]

# ====== 題目與選單函式 ======
def send_start_menu(reply_token):
    flex_message = FlexSendMessage(alt_text='開始選單', contents={"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "歡迎！", "weight": "bold", "size": "xl"}, {"type": "text", "text": "請選擇您的下一步動作：", "margin": "md"}, {"type": "button", "action": {"type": "message", "label": "進入遊戲", "text": "進入遊戲"}, "style": "primary", "color": "#5A94C7", "margin": "xxl"}, {"type": "button", "action": {"type": "message", "label": "兌換獎項", "text": "兌換獎項"}, "style": "secondary", "margin": "md"}]}})
    line_bot_api.reply_message(reply_token, flex_message)

def send_question_1(user_id):
    flex_message = { "type": "bubble", "hero": {"type": "image", "url": "https://github.com/chengzi08/tsse-linebot/blob/main/Q1.png?raw=true", "size": "full", "aspectRatio": "1.51:1", "aspectMode": "fit"}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第一題：誰是飛天小女警的角色？", "weight": "bold", "size": "md", "margin": "md"}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A 泡泡", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B 豆豆", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C 毛毛", "text": "C"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第一題", contents=flex_message))

def send_question_2(user_id):
    flex_message = {"type": "bubble", "hero": {"type": "image", "url": "https://github.com/chengzi08/tsse-linebot/blob/main/Q2.png?raw=true", "size": "full", "aspectRatio": "1.51:1", "aspectMode": "fit"}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第二題：一次函數 y＝－2x－6 通過哪個點？", "weight": "bold", "size": "md", "margin": "md", "wrap": True}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A (-4, 1)", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B (-4, 2)", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C (-4, -2)", "text": "C"}}, {"type": "button", "style": "primary", "color": "#FFD966", "action": {"type": "message", "label": "D (-4, -1)", "text": "D"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第二題", contents=flex_message))

def send_question_3(user_id):
    flex_message = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第三題：多少個正整數是 18 的倍數，也是 216 的因數？", "weight": "bold", "size": "md", "margin": "md", "wrap": True}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A 2", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B 6", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C 10", "text": "C"}}, {"type": "button", "style": "primary", "color": "#FFD966", "action": {"type": "message", "label": "D 12", "text": "D"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第三題", contents=flex_message))

def send_question_4(user_id):
    flex_message = { "type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "第四題：一份套餐比單點雞排+可樂便宜40元，\n單點雞排送一片+兩杯可樂，比兩份套餐便宜10元。\n根據敘述，哪個為正確結論？", "weight": "bold", "size": "md", "margin": "md", "wrap": True}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#6EC1E4", "action": {"type": "message", "label": "A 套餐140", "text": "A"}}, {"type": "button", "style": "primary", "color": "#A3D977", "action": {"type": "message", "label": "B 套餐120", "text": "B"}}, {"type": "button", "style": "primary", "color": "#F7B2B7", "action": {"type": "message", "label": "C 雞排90", "text": "C"}}, {"type": "button", "style": "primary", "color": "#FFD966", "action": {"type": "message", "label": "D 雞排70", "text": "D"}}]}]}}
    line_bot_api.push_message(user_id, FlexSendMessage(alt_text="第四題", contents=flex_message))

def send_question_5(user_id):
    line_bot_api.push_message(user_id, TextSendMessage(text="太棒了！這是最後一關：\n\n請上傳一張你最喜歡的照片，完成最後的挑戰！"))


# ====== 啟動 ======
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
