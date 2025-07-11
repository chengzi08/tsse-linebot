import os
import pytz
import datetime
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, ImageSendMessage, ImageMessage
)

import gspread
from PIL import Image, ImageDraw, ImageFont 
import io 
import requests 
import json 

app = Flask(__name__)

# ====== 環境變數與 API 初始化 ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_SHEET_NAME = os.environ.get('GOOGLE_SHEET_NAME')

# 假設 Render Secret File 路徑
SERVICE_ACCOUNT_FILE = '/etc/secrets/google_credentials.json'

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GOOGLE_SHEET_NAME]):
    print("警告：請確認所有必要的環境變數已設定。")

# --- Google Sheets 初始化 ---
try:
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open(GOOGLE_SHEET_NAME)
    worksheet = sh.sheet1
    print("成功連接 Google Sheet")
except Exception as e:
    worksheet = None
    print(f"Google Sheet 連接失敗: {e}")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 使用者狀態記錄 ======
user_states = {}

# ====== 核心函式：取得玩家資訊  ======
def get_player_info(user_id):
    global worksheet
    if not worksheet: return None
    try:
        cells = worksheet.findall(user_id, in_column=5) # E欄是 LINE User ID
        if not cells:
            all_player_ids = worksheet.col_values(8)[1:] # H欄是玩家永久編號
            all_player_ids_int = [int(i) for i in all_player_ids if i and i.isdigit()]
            new_id = max(all_player_ids_int) + 1 if all_player_ids_int else 1
            return {'id': new_id, 'play_count': 1, 'is_new': True}
        else:
            first_cell = cells[0]
            permanent_id_str = worksheet.cell(first_cell.row, 8).value # H欄
            permanent_id = int(permanent_id_str) if permanent_id_str and permanent_id_str.isdigit() else 0
            all_play_counts = [int(worksheet.cell(c.row, 9).value) for c in cells if worksheet.cell(c.row, 9).value and worksheet.cell(c.row, 9).value.isdigit()] # I欄
            next_play_count = max(all_play_counts) + 1 if all_play_counts else 1
            return {'id': permanent_id, 'play_count': next_play_count, 'is_new': False}
    except Exception as e:
        print(f"獲取玩家資訊時出錯: {e}")
        return None

# ====== 核心函式：寫入紀錄  ======
def record_completion(user_id):
    global worksheet
    if not worksheet: return None
    state = user_states.get(user_id, {})
    if 'player_info' not in state: return None
    player_info = state['player_info']
    is_first_ever_completion = player_info['is_new']
    
    # 檢查玩家過去是否已兌獎
    has_redeemed_before = False
    try:
        all_user_records = worksheet.findall(user_id, in_column=5) # E欄是 User ID
        for record_cell in all_user_records:
            if worksheet.cell(record_cell.row, 6).value == '是':
                has_redeemed_before = True
                break
    except Exception as e:
        print(f"檢查過往兌獎狀態時發生錯誤: {e}")
        has_redeemed_before = False

    try:
        tpe_timezone = pytz.timezone('Asia/Taipei')
        completion_time = datetime.datetime.now(tpe_timezone)
        duration_seconds = round((completion_time - state['start_time']).total_seconds(), 2)
        
        row_to_insert = [
            f"{player_info['id']}-{player_info['play_count']}",
            state['name'],
            completion_time.strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds,
            user_id,
            "是" if has_redeemed_before else "否", # F欄: 是否已兌獎
            "是" if is_first_ever_completion else "否",
            player_info['id'],
            player_info['play_count']
        ]
        worksheet.insert_row(row_to_insert, 2)
        return {'is_first': is_first_ever_completion, 'count': player_info['play_count']}
    except Exception as e:
        print(f"寫入 Google Sheet 時發生錯誤: {e}")
        return None

# ====== 核心函式：兌換獎品 (不變) ======
def redeem_prize(user_id):
    global worksheet
    if not worksheet: return None
    try:
        cell = worksheet.find(user_id, in_column=5) # E欄是 LINE User ID
        if not cell:
            return 'not_found'
        
        # F欄是是否已兌獎
        if worksheet.acell(f'F{cell.row}').value == '是':
            return 'already_redeemed'
        
        worksheet.update_acell(f'F{cell.row}', '是')
        return 'success'
    except Exception as e:
        print(f"兌獎時發生錯誤: {e}")
        return None

# ★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★    排行榜核心函式 (最終版)    ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★

def get_leaderboard():
    """
    從 Google Sheet 讀取資料，產生排行榜文字。
    使用欄位索引來讀取，避免因標頭名稱不符而出錯。
    """
    if not worksheet:
        print("排行榜功能：Worksheet 未初始化。")
        return "抱歉，排行榜功能暫時無法使用，請聯繫管理員。"

    try:
        # 1. 讀取整個工作表的所有值 (除了第一行標頭)
        all_values = worksheet.get_all_values()[1:]

        if not all_values:
            return "目前還沒有人完成挑戰，快來搶頭香吧！🏆"

        # 2. 篩選出首次通關的紀錄
        #    我們假設 B欄(索引1)是名稱，D欄(索引3)是時間，G欄(索引6)是首次通關標記
        first_completion_records = []
        for row in all_values:
            # 檢查 G 欄 (索引 6) 是否為 '是'
            # 並且檢查 D 欄 (索引 3) 是否有時間值
            if len(row) > 6 and row[6].strip() == '是' and len(row) > 3 and row[3]:
                try:
                    name = row[1]
                    time_spent = float(row[3])
                    first_completion_records.append({'name': name, 'time': time_spent})
                except (ValueError, IndexError):
                    # 如果時間格式不對或該行資料不完整，就跳過這筆紀錄
                    continue
        
        if not first_completion_records:
            return "目前還沒有玩家首次完成挑戰！"
            
        # 3. 根據時間進行排序 (時間越少越前面)
        sorted_records = sorted(first_completion_records, key=lambda x: x['time'])

        # 4. 取出前 5 名並格式化輸出文字
        top_5_records = sorted_records[:5]

        leaderboard_text = "🏆 積分計時排行榜 🏆\n\n"
        rank_emojis = ["🥇", "🥈", "🥉", "⒋", "⒌"]

        for i, record in enumerate(top_5_records):
            rank = rank_emojis[i]
            name = record.get('name', '匿名玩家')
            time_spent = record.get('time', 'N/A')
            leaderboard_text += f"{rank} {name} - {time_spent} 秒\n"

        return leaderboard_text.strip()

    except gspread.exceptions.APIError as e:
        print(f"Google Sheets API 錯誤: {e}")
        return "讀取排行榜時發生 API 錯誤，請檢查權限或稍後再試。"
    except Exception as e:
        print(f"產生排行榜時發生未預期的錯誤: {e}")
        return "讀取排行榜時發生了一點小問題，請稍後再試！"

# ====== Webhook 入口 (不變) ======
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'
# ====== ★ 圖片判讀 ★ ======
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    reply_token = event.reply_token

    state = user_states.get(user_id)
    if not state: return

    # 檢查是否在第三關等待圖片
    if state.get('progress') == 3:
        state['progress'] = 4 # 進度推進到第四關
        
        # 準備回覆訊息和下一關題目
        reply_text = TextSendMessage(text="哇！整個場館你最夏啪！")
        q4_flex = FlexSendMessage(alt_text="第四關", contents=get_question_4_flex()) # 使用輔助函式取得 JSON
        
        # 一次性回覆並發送第四關
        line_bot_api.reply_message(reply_token, messages=[reply_text, q4_flex])

# ====== ★ 修改後的處理文字訊息 (優化費用) ★ ======
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    reply_token = event.reply_token

    # 最高層級指令
    if user_message == "開始遊戲":
        # 如果玩家中途重來，清除舊狀態
        if user_id in user_states:
            del user_states[user_id]
        # 設定一個初始狀態，代表還沒進入遊戲
        user_states[user_id] = {'progress': 0}
        # 呼叫新的選單函式
        send_game_entry_menu(reply_token)
        return
    if user_message == "排行榜":
            print("====== 觸發排行榜功能 ======")
            leaderboard_text = get_leaderboard()
            print(f"排行榜函式回傳內容: {leaderboard_text}")
            if not leaderboard_text:
                leaderboard_text = "抱歉，目前無法取得排行榜資料。"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=leaderboard_text))
            print("====== 排行榜訊息已發送 ======")
            return
    # ★★★★★★★★★★★★★★★★★★★★★★★★★
    # ★     這裡是新增的「進入遊戲」邏輯   ★
    # ★★★★★★★★★★★★★★★★★★★★★★★★★
    elif user_message == "進入遊戲":
        state = user_states.get(user_id)
        # 確保玩家是從「開始遊戲」進來的 (progress 應為 0)
        if state and state.get('progress') == 0:
            state['progress'] = -1 # 將進度設為 -1 (等待姓名)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="歡迎來到問答挑戰！\n請輸入您想在遊戲中使用的名稱："))
        else:
            # 如果玩家亂打「進入遊戲」，引導他先「開始遊戲」
            line_bot_api.reply_message(reply_token, TextSendMessage(text="請先輸入「開始遊戲」喔！"))
        return


    elif user_message == "週末限定活動報名":
        flex_link_message = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "週末限定活動", "weight": "bold", "size": "xl"}, {"type": "text", "text": "名額有限，請點擊下方按鈕立即報名！", "margin": "md", "wrap": True}, {"type": "separator", "margin": "xxl"}, {"type": "button", "style": "primary",  "color": "#4D96FF", "margin": "xl", "height": "sm", "action": {"type": "uri", "label": "點我前往報名", "uri": "https://docs.google.com/forms/d/e/1FAIpQLSc28lR_7rCNwy7JShQBS9ags6DL0NinKXIUIDJ4dv6YwAIzuA/viewform?usp=dialog"}}]}}
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="週末限定活動報名連結", contents=flex_link_message))
        return

    elif user_message == "活動介紹":
        image_url = "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/ation-v3.jpg"
        line_bot_api.reply_message(reply_token, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        return
        
    elif user_message == "平日常態活動":
        image_url = "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/week-V1.jpg"
        line_bot_api.reply_message(reply_token, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        return
    
    state = user_states.get(user_id)
    if not state:
        return
        
    progress = state.get('progress', 0)

    # ★ 優化點 1: 輸入姓名後，合併回覆歡迎詞和第一題 (免費)
    if progress == -1:
        player_name = user_message
        player_info = get_player_info(user_id)
        if not player_info:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="抱歉，無法讀取玩家資料，請稍後再試。"))
            return

        state.update({'name': player_name, 'player_info': player_info, 'start_time': datetime.datetime.now(pytz.timezone('Asia/Taipei')), 'progress': 1})
        
        # 準備兩則訊息
        reply_text = f"你好，{player_name}！\n你的挑戰編號是 {player_info['id']}-{player_info['play_count']} 號。\n\n遊戲現在開始！"
        welcome_message = TextSendMessage(text=reply_text)
        # 使用輔助函式取得第一題的 Flex JSON
        q1_flex = FlexSendMessage(alt_text="第一題", contents=get_question_1_flex())
        
        # 合併在一個 reply_message 中發送
        line_bot_api.reply_message(reply_token, messages=[welcome_message, q1_flex])
        return

    # ★ 優化點 2: 答題過程全部改用 reply_token (免費)
    if progress == 1:
        if user_message == "B":
            state['progress'] = 2
            send_question_2(reply_token)
        else:
            image_url = "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q1-A.jpg"
            image_message = ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            text_message = TextSendMessage(text="再仔細看看!!!在第10-15頁之間!～")
            line_bot_api.reply_message(reply_token, messages=[image_message, text_message])

    elif progress == 2:
        if user_message == "C":
            state['progress'] = 3
            send_question_3(reply_token)
        else:
            image_url = "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q2-A.jpg"
            image_message = ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            text_message = TextSendMessage(text="答錯了！抵達萬花筒區域就可以找到正確解答!")
            line_bot_api.reply_message(reply_token, messages=[image_message, text_message])

    elif progress == 3:
        pass

    elif progress == 4:
        if user_message == "我已拍照打卡完畢":
            
            # 1. 記錄成績
            record_result = record_completion(user_id)
            
            # 2. 將進度設為 5 (等待兌換狀態)
            state['progress'] = 5
            
            # 3. 準備並傳送最終的 Flex 選單
            if record_result:
                final_flex = get_final_redemption_menu(record_result)
                line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="恭喜通關！", contents=final_flex))
            else:
                # 如果記錄失敗，回傳錯誤訊息
                final_message = "恭喜通關！但在記錄成績時發生錯誤，請聯繫管理員。"
                line_bot_api.reply_message(reply_token, TextSendMessage(text=final_message))
                # 記錄失敗時，直接清除玩家狀態
                if user_id in user_states:
                    del user_states[user_id]
        else:
            # 如果使用者在第四關亂打字，不回應
            pass
            
               # 點擊通關畫面的 "兌換獎項" 按鈕
    elif progress == 5 and user_message == "兌換獎項":
        state['progress'] = -2
        line_bot_api.reply_message(reply_token, TextSendMessage(text="請將手機交給工作人員，並由工作人員輸入兌換碼："))
        return
    
    # 輸入兌換碼
    if progress == -2:
        if user_message == "PASS":
            result = redeem_prize(user_id)
            reply_text = {'success': "獎項兌換成功！", 'already_redeemed': "您已兌換過獎品囉！", 'not_found': "您尚未完成遊戲挑戰，無法兌換獎品喔！"}.get(result, "兌換時發生錯誤，請聯繫管理員。")
            if user_id in user_states: del user_states[user_id] # 兌換後清除狀態
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="兌換碼錯誤，請重新輸入。"))
        return

# ====== ★ 題目與選單函式 (修改為使用 reply_token) ★ ======
def send_start_menu(reply_token):
    flex_message = FlexSendMessage(alt_text='開始選單', contents={"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "歡迎！", "weight": "bold", "size": "xl"}, {"type": "text", "text": "請選擇您的下一步動作：", "margin": "md"}, {"type": "button", "action": {"type": "message", "label": "進入遊戲", "text": "進入遊戲"}, "style": "primary", "color": "#5A94C7", "margin": "xxl"}, {"type": "button", "action": {"type": "message", "label": "兌換獎項", "text": "兌換獎項"}, "style": "secondary", "margin": "md"}]}})
    line_bot_api.reply_message(reply_token, flex_message)

def send_game_entry_menu(reply_token):
    """
    發送包含「進入遊戲」和「排行榜」按鈕的 Flex Message。
    """
    flex_message = FlexSendMessage(
        alt_text='歡迎來到問答挑戰',
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "歡迎來到問答挑戰！",
                        "weight": "bold",
                        "size": "xl"
                    },
                    {
                        "type": "text",
                        "text": "準備好就進入遊戲，或先看看高手們的紀錄！",
                        "margin": "md",
                        "wrap": True
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "xxl",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "action": {
                                    "type": "message",
                                    "label": "進入遊戲",
                                    "text": "進入遊戲"
                                },
                                "style": "primary",
                                "color": "#4D96FF",
                                "height": "sm"
                            },
                            {
                                "type": "button",
                                "action": {
                                    "type": "message",
                                    "label": "排行榜",
                                    "text": "排行榜"
                                },
                                "style": "secondary",
                                "height": "sm"
                            }
                        ]
                    }
                ]
            }
        }
    )
    line_bot_api.reply_message(reply_token, flex_message)

# ★ 新增輔助函式，用於取得第一題的 Flex JSON
# ★ 修改點 ★
def get_question_1_flex():
    # 注意：請將圖片 URL 換成您自己的
    return {"type": "bubble", "hero": {"type": "image", "url": "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q1-V1.jpg", "size": "full", "aspectRatio": "1.51:1", "aspectMode": "fit"}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "關卡一：找找我在哪", "weight": "bold", "size": "lg"}, {"type": "text", "text": "找到這本神秘的大書，從左邊翻開數第8頁，數數看，圖片中有幾隻雞呢?", "margin": "md", "wrap": True}, {"type": "separator", "margin": "lg"}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary",  "color": "#4D96FF","action": {"type": "message", "label": "A：５隻雞", "text": "A"}}, {"type": "button", "style": "primary", "color": "#4D96FF", "action": {"type": "message", "label": "B：７隻雞", "text": "B"}}, {"type": "button", "style": "primary", "color": "#4D96FF", "action": {"type": "message", "label": "C：９隻雞", "text": "C"}}, {"type": "button", "style": "primary", "color": "#4D96FF", "action": {"type": "message", "label": "D：沒有雞", "text": "D"}}]}]}}

def send_question_2(reply_token):
    # 注意：請將圖片 URL 換成您自己的
    flex_message = {"type": "bubble", "hero": {"type": "image", "url": "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q2-V2.jpg", "size": "full", "aspectRatio": "1.51:1", "aspectMode": "fit"}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "關卡二：尋找寶藏 ─ 拼圖遊戲", "weight": "bold", "size": "lg"}, {"type": "text", "text": "手腦並用完成拼圖挑戰，拼出藏寶路線圖。\n請問王博士得到的寶藏是什麼呢？", "margin": "md", "wrap": True}, {"type": "separator", "margin": "lg"}, {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#4D96FF", "action": {"type": "message", "label": "糖果", "text": "A"}}, {"type": "button", "style": "primary", "color": "#4D96FF", "action": {"type": "message", "label": "水槍", "text": "B"}}, {"type": "button", "style": "primary",  "color": "#4D96FF","action": {"type": "message", "label": "草莓", "text": "C"}}, {"type": "button", "style": "primary", "color": "#4D96FF", "action": {"type": "message", "label": "小兔子", "text": "D"}}]}]}}
    line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="第二關", contents=flex_message))

def send_question_3(reply_token):
    # 注意：請將圖片 URL 換成您自己的
    reply_text = "關卡三：全場我最亮 ─ 與飛天小女警拍美照\n\n找到場館內的飛天小女警打卡區，戴上夏啪拍照小物再拍張照，今夏的美好回憶全在台塑生醫健康悠活館！\n\n拍完照記得利用訊息傳回來給我們唷～"
    q3_image = ImageSendMessage(
        original_content_url="https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q3.jpg",
        preview_image_url="https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q3.jpg"
    )
    line_bot_api.reply_message(reply_token, messages=[q3_image, TextSendMessage(text=reply_text)])

def get_question_4_flex():
    # 注意：請將圖片 URL 換成您自己的
    return {"type": "bubble", "hero": {"type": "image", "url": "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q4-V1.png", "size": "full", "aspectRatio": "1.51:1", "aspectMode": "fit"}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "關卡四：台塑生醫 x 飛天小女警", "weight": "bold", "size": "lg"}, {"type": "text", "text": "在商品銷售區找到聯名商品，拍張照並上傳到社群，打卡在台塑生醫健康悠活館，並出示給販售區工作人員，即可得到飛天小女警的扇子！", "margin": "md", "wrap": True}]}, "footer": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "我已拍照打卡完畢，請工作人員審核並點選", "wrap": True, "align": "center", "size": "sm"}, {"type": "button", "style": "primary",  "color": "#4D96FF", "margin": "md", "action": {"type": "message", "label": "確認審核", "text": "我已拍照打卡完畢"}}]}}

def get_final_redemption_menu(record_result):
    title = "🎉 恭喜你完成所有挑戰！🎊" if record_result['is_first'] else "🎉 挑戰成功！🎉"
    body_text = "您的成績已成功記錄！" if record_result['is_first'] else f"這是您的第 {record_result['count']} 次通關紀錄！"
    
    return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [{"type": "text", "text": title, "weight": "bold", "size": "xl", "wrap": True, "align": "center"}, {"type": "text", "text": body_text, "align": "center", "wrap": True}, {"type": "separator", "margin": "lg"}, {"type": "text", "text": "您的兌換碼為【PASS】。", "margin": "lg", "weight": "bold", "align": "center"}, {"type": "text", "text": "（請將此畫面出示給關主，由關主為您操作兌換，請勿自行輸入）", "wrap": True, "size": "xs", "align": "center", "color": "#888888"}, {"type": "button", "style": "primary", "color": "#4D96FF", "margin": "xl", "action": {"type": "message", "label": "兌換獎項", "text": "兌換獎項"}}]}}

# ====== 啟動 ======
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
