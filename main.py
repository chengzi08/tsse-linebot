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
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★ 這行已經被完全刪除，因為 CellNotFound 不再存在 ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

app = Flask(__name__)

# ====== 環境變數與 API 初始化 (省略部分 print) ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_SHEET_NAME = os.environ.get('GOOGLE_SHEET_NAME')
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GOOGLE_SHEET_NAME, GOOGLE_DRIVE_FOLDER_ID]):
    print("警告：請確認所有環境變數 (LINE..., GOOGLE_SHEET_NAME, GOOGLE_DRIVE_FOLDER_ID) 已設定。")

try:
    SERVICE_ACCOUNT_FILE = '/etc/secrets/google_credentials.json'
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open(GOOGLE_SHEET_NAME)
    worksheet = sh.sheet1
    print("成功連接 Google Sheet")
except Exception as e:
    worksheet = None
    print(f"Google Sheet 連接失敗: {e}")

try:
    gauth = GoogleAuth()
    gauth.credentials = gspread.auth.load_credentials(SERVICE_ACCOUNT_FILE)
    drive = GoogleDrive(gauth)
    print("成功初始化 Google Drive Client")
except Exception as e:
    drive = None
    print(f"Google Drive Client 初始化失敗: {e}")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 使用者狀態記錄 ======
user_states = {}

# ====== 核心函式：取得玩家資訊 (不變) ======
def get_player_info(user_id):
    if not worksheet: return None
    try:
        cells = worksheet.findall(user_id, in_column=5) # E欄是 LINE User ID
        if not cells:
            all_player_ids = worksheet.col_values(9)[1:] # 讀取I欄 (玩家永久編號)
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

# ====== 核心函式：寫入紀錄 (不變) ======
def record_completion(user_id, image_url=None):
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

# ====== ★★★★★★★★★★★★★ 核心函式：兌換獎品 (已修正) ★★★★★★★★★★★★★ ======
def redeem_prize(user_id):
    """處理兌獎邏輯。回傳: 'success', 'already_redeemed', 'not_found'"""
    if not worksheet: return None
    try:
        # 尋找 E 欄中符合 user_id 的儲存格
        cell = worksheet.find(user_id, in_column=5) # E欄是 LINE User ID

        # ★ 關鍵修改：用 if not cell 判斷是否找到
        if not cell:
            # 如果找不到 user_id，代表玩家還沒通關
            return 'not_found'

        # 如果程式能走到這裡，代表 cell 找到了
        redeem_status_cell = f'G{cell.row}' # G欄是是否已兌獎
        if worksheet.acell(redeem_status_cell).value == '是':
            return 'already_redeemed'
        
        # 更新 G 欄為 "是"
        worksheet.update_acell(redeem_status_cell, '是')
        return 'success'
        
    except Exception as e:
        # 捕捉其他可能的錯誤，例如網路問題
        print(f"兌獎時發生錯誤: {e}")
        return None
    
# ====== Webhook 入口 (不變) ======
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

# ====== 處理文字訊息 (不變) ======
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    reply_token = event.reply_token
    state = user_states.setdefault(user_id, {'progress': 0})
    progress = state.get('progress', 0)
    
    if user_message == "開始遊戲" and progress == 0:
        send_start_menu(reply_token)
        return
    
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
            if result == 'success': reply_text = "獎項兌換成功！"
            elif result == 'already_redeemed': reply_text = "您已兌換過獎品囉！"
            elif result == 'not_found': reply_text = "您尚未完成遊戲挑戰，無法兌換獎品喔！"
            else: reply_text = "兌換時發生錯誤，請聯繫管理員。"
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
            
    elif progress == 0:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="請輸入「開始遊戲」來選擇下一步動作。"))

# ====== 處理圖片訊息 (不變) ======
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
            for chunk in message_content.iter_content(): fd.write(chunk)

        drive_file = drive.CreateFile({'title': f'{user_id}-{event.message.id}.jpg', 'parents': [{'id': GOOGLE_DRIVE_FOLDER_ID}]})
        drive_file.SetContentFile(temp_file_path)
        drive_file.Upload()
        drive_file.InsertPermission({'type': 'anyone', 'value': 'anyone', 'role': 'reader'})
        image_url = drive_file['webViewLink']

        record_result = record_completion(user_id, image_url=image_url)
        if record_result:
            if record_result['is_first']: final_message = "🎉 照片上傳成功，恭喜你完成所有挑戰！🎊\n您的成績已成功記錄！"
            else: final_message = f"🎉 挑戰成功！這是您的第 {record_result['count']} 次通關紀錄！"
        else:
            final_message = "恭喜通關！但在記錄成績時發生錯誤，請聯繫管理員。"
        line_bot_api.push_message(user_id, TextSendMessage(text=final_message))
    except Exception as e:
        print(f"圖片處理失敗: {e}")
        line_bot_api.push_message(user_id, TextSendMessage(text="啊！照片上傳失敗了...請再試一次。"))
    finally:
        if os.path.exists(temp_file_path): os.remove(temp_file_path)
        if user_id in user_states: del user_states[user_id]

# ====== 題目與選單函式 (不變) ======
def send_start_menu(reply_token):
    #... (內容省略)
    pass
def send_question_1(user_id):
    #... (內容省略)
    pass
#... (其他 send_question 函式內容省略)

# ====== 啟動 ======
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
