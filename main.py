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
from PIL import Image, ImageDraw, ImageFont # ★ 新增
import io # ★ 新增
import requests # ★ 新增
import json # ★ 新增

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

# ====== 核心函式：取得玩家資訊 (不變) ======
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

# ====== 核心函式：寫入紀錄 (不變) ======
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

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★    全新功能：動態生成個人化成績單函式         ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
def create_report_card(player_name, time_spent):
    try:
        # 1. 開啟背景圖範本
        template_path = "report_card_template.png" 
        img = Image.open(template_path)
        draw = ImageDraw.Draw(img)

        # 2. 載入字型檔
        font_path = "NotoSansTC-Bold.otf" 
        name_font = ImageFont.truetype(font_path, size=48)
        time_font = ImageFont.truetype(font_path, size=36)

        # 3. 準備文字內容
        name_text = f"玩家：{player_name}"
        time_text = f"通關時間：{time_spent} 秒"

        # 4. ★★★ 您需要手動調整這裡的 (x, y) 座標 ★★★
        # (0,0) 是圖片左上角，請根據您的背景圖調整文字位置
        draw.text((100, 150), name_text, font=name_font, fill=(255, 255, 255)) # 白色字
        draw.text((100, 220), time_text, font=time_font, fill=(255, 255, 255)) # 白色字

        # 5. 在記憶體中儲存圖片，準備上傳
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        # 6. 上傳到 Postimages
        print("正在上傳成績單到 Postimages...")
        response = requests.post("https://postimages.org/json/v1/upload", files={'file': ('report_card.png', img_byte_arr, 'image/png')})
        
        if response.status_code == 200:
            result = response.json()
            if result.get('status') == 'OK':
                image_url = result.get('url')
                print(f"成績單上傳成功！URL: {image_url}")
                return image_url
        
        print(f"Postimages 上傳失敗: {response.text}")
        return None

    except FileNotFoundError:
        print("錯誤：找不到 report_card_template.png 或 NotoSansTC-Bold.otf！")
        return None
    except Exception as e:
        print(f"生成成績單時發生錯誤: {e}")
        return None


# ★★★★★★★★★★★★★★★★★★★★★★★★★
# ★    這裡是新增的排行榜核心函式    ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★

def get_leaderboard():
    """
    從 Google Sheet 讀取資料，產生排行榜文字。
    回傳格式化後的文字，如果出錯或沒有資料則回傳 None。
    """
    if not worksheet:
        print("排行榜功能：Worksheet 未初始化。")
        return "抱歉，排行榜功能暫時無法使用，請聯繫管理員。"

    try:
        # 取得所有紀錄 (假設第一行為標頭，所以從第二行開始)
        # worksheet.get_all_records() 會將每一行轉成字典，很方便
        records = worksheet.get_all_records()

        if not records:
            return "目前還沒有人完成挑戰，快來搶頭香吧！🏆"

         # 清理所有記錄的鍵，去除前後空格
        cleaned_records = []
        for record in records:
            cleaned_record = {key.strip(): value for key, value in record.items()}
            cleaned_records.append(cleaned_record)
        
        # 接下來都使用 cleaned_records
        records = cleaned_records

        # 現在，在這裡定義您 Sheet 中確切的欄位名稱 (從 Sheet 複製貼上)
        TIME_COLUMN_HEADER = '總花費時間(秒)' # <-- 把這裡換成您從 Sheet 複製的標頭
        NAME_COLUMN_HEADER = '玩家名稱(B)'   # <-- 確認這個也正確
        FIRST_TIME_COLUMN_HEADER = '是否為首次通關(G)' # <-- 確認這個也正確
        
        first_completion_records = [
            r for r in records if str(r.get(FIRST_TIME_COLUMN_HEADER, '否')).strip() == '是'
        ]

        if not first_completion_records:
            return "目前還沒有玩家首次完成挑戰！"
            
        for record in first_completion_records:
            try:
                record[TIME_COLUMN_HEADER] = float(record[TIME_COLUMN_HEADER])
            except (ValueError, TypeError):
                record[TIME_COLUMN_HEADER] = float('inf')

        sorted_records = sorted(first_completion_records, key=lambda x: x[TIME_COLUMN_HEADER])

        top_5_records = sorted_records[:5]

        leaderboard_text = "🏆 積分計時排行榜 🏆\n\n"
        rank_emojis = ["🥇", "🥈", "🥉", "⒋", "⒌"]

        for i, record in enumerate(top_5_records):
            rank = rank_emojis[i]
            name = record.get(NAME_COLUMN_HEADER, '匿名玩家')
            time_spent = record.get(TIME_COLUMN_HEADER, 'N/A')
            leaderboard_text += f"{rank} {name} - {time_spent} 秒\n"

        return leaderboard_text.strip()

    except Exception as e:
        print(f"產生排行榜時發生錯誤: {e}")
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

    # 最高層級指令 (不變)
    # 最高層級指令
    if user_message == "開始遊戲":
        if user_id in user_states:
            del user_states[user_id]
        user_states[user_id] = {'progress': -1}
        line_bot_api.reply_message(reply_token, TextSendMessage(text="歡迎來到問答挑戰！\n請輸入您想在遊戲中使用的名稱："))
        return

    # ★★★★★★★★★★★★★★★★★★★★★★★★★
    # ★    這裡是新增的排行榜觸發點    ★
    # ★★★★★★★★★★★★★★★★★★★★★★★★★
    elif user_message == "排行榜":
        # 呼叫我們剛剛建立的函式來取得排行榜文字
        leaderboard_text = get_leaderboard()
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=leaderboard_text)
        )
        return


    elif user_message == "週末限定活動報名":
        flex_link_message = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "週末限定活動", "weight": "bold", "size": "xl"}, {"type": "text", "text": "名額有限，請點擊下方按鈕立即報名！", "margin": "md", "wrap": True}, {"type": "separator", "margin": "xxl"}, {"type": "button", "style": "primary",  "color": "#4D96FF", "margin": "xl", "height": "sm", "action": {"type": "uri", "label": "點我前往報名", "uri": "https://docs.google.com/forms/d/e/1FAIpQLSc28lR_7rCNwy7JShQBS9ags6DL0NinKXIUIDJ4dv6YwAIzuA/viewform?usp=dialog"}}]}}
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="週末限定活動報名連結", contents=flex_link_message))
        return

    elif user_message == "活動介紹":
        image_url = "https://github.com/chengzi08/tsse-linebot/blob/main/ation-v2.jpg?raw=true"
        line_bot_api.reply_message(reply_token, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        return
        
    elif user_message == "平日常態活動":
        reply_text = "" 
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text.strip()))
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
        if user_message == "B": # 假設 "9隻雞" 是正確答案
            state['progress'] = 2
            send_question_2(reply_token)
        else:
            image_url = "https://raw.githubusercontent.com/chengzi08/tsse-linebot/main/Q1-A.jpg"
            image_message = ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            )
            text_message = TextSendMessage(text="答案不正確！看圖片再試一次")
            line_bot_api.reply_message(
                reply_token,
                messages=[image_message, text_message]
            )
            
            # 3. 將兩個訊息放進一個 list，並一起傳送
        line_bot_api.reply_message(
                reply_token,
                messages=[image_message, text_message] # 注意這裡是 messages=[...]
            )
            
            # 使用 reply_message 傳送圖片
        line_bot_api.reply_message(reply_token, wrong_answer_message)
    elif progress == 2:
        if user_message == "C":
            state['progress'] = 3
            send_question_3(reply_token) # 傳入 reply_token
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="錯誤答案！重來看看～")) # 改用 reply
    elif progress == 3:
            pass
    elif progress == 4:
        if user_message == "我已拍照打卡完畢":
            # 1. 先回覆處理中訊息，避免超時
            line_bot_api.reply_message(reply_token, TextSendMessage(text="挑戰完成！正在為您製作專屬成績單...請稍候片刻 ✨"))
            
            # 2. 準備生成成績單所需的資料
            state_data = user_states.get(user_id, {})
            player_name = state_data.get('name', '挑戰者')
            start_time = state_data.get('start_time', datetime.datetime.now(pytz.timezone('Asia/Taipei')))
            time_spent = round((datetime.datetime.now(pytz.timezone('Asia/Taipei')) - start_time).total_seconds(), 2)

            # 3. 生成成績單
            report_card_url = create_report_card(player_name, time_spent)

            # 4. 記錄到 Google Sheet
            record_result = record_completion(user_id)
            state['progress'] = 5 # 進入等待兌換狀態

            # 5. 準備最終要發送的訊息
            messages_to_send = []
            if report_card_url:
                messages_to_send.append(ImageSendMessage(original_content_url=report_card_url, preview_image_url=report_card_url))
            
            if record_result:
                final_flex = get_final_redemption_menu(record_result)
                messages_to_send.append(FlexSendMessage(alt_text="恭喜通關！", contents=final_flex))
            else:
                messages_to_send.append(TextSendMessage(text="恭喜通關！但在記錄成績時發生錯誤。"))

            # 6. 使用 push_message 發送 (因為 reply_token 已用掉)
            if messages_to_send:
                line_bot_api.push_message(user_id, messages=messages_to_send)
        else:
            pass # 如果在第四關亂打字，不回應
            
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
