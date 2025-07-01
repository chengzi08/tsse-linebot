import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction

app = Flask(__name__)

# 從環境變數中取得金鑰
# 部署到 Render 時，我們會把金鑰設定在環境變數中，而不是寫死在程式碼裡
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

# 確認金鑰是否存在
if LINE_CHANNEL_ACCESS_TOKEN is None or LINE_CHANNEL_SECRET is None:
    print("請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
    # 在本地測試時，如果沒有設定，可以先用下面的假資料，但部署時務必刪除或註解掉
    # LINE_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"
    # LINE_CHANNEL_SECRET = "YOUR_CHANNEL_SECRET"
    # exit() # 部署時建議打開，如果抓不到金鑰就直接停止服務

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 使用者進度狀態記錄（正式建議改為資料庫）======
user_progress = {}  # user_id -> 第幾題

# ====== Webhook 入口（需設定在 LINE Developer 的 Webhook URL）======
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
    user_message = event.message.text
    reply_token = event.reply_token

    # 首次進入遊戲
    if user_message == "選單":
        start_action = MessageAction(label="開始遊戲", text="開始遊戲")
        quick_reply_buttons = QuickReply(items=[
            QuickReplyButton(action=start_action)
        ])
        message = TextSendMessage(
            text="歡迎來到問答遊戲，請點選開始！",
            quick_reply=quick_reply_buttons
        )
        line_bot_api.reply_message(reply_token, message)
        return

    # 開始遊戲
    if user_message == "開始遊戲":
        user_progress[user_id] = 1
        send_question_1(reply_token)
        return

    # 讀取目前進度
    progress = user_progress.get(user_id, 0)

    # 題目邏輯
    if progress == 1:
        if user_message == "A":
            user_progress[user_id] = 2
            send_question_2(reply_token)
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="答錯囉～再試試看！"))
    elif progress == 2:
        if user_message == "C":
            user_progress[user_id] = 3
            send_question_3(reply_token)
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="錯誤答案！重來看看～"))
    elif progress == 3:
        if user_message == "B":
            user_progress[user_id] = 4
            send_question_4(reply_token)
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="這不是正確答案喔～再試一次！"))
    elif progress == 4:
        if user_message == "B":
            line_bot_api.reply_message(reply_token, TextSendMessage(text="🎉 恭喜你全部答對！你完成了通關～🎊"))
            user_progress[user_id] = 0  # 重置遊戲
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="最後一題答錯了，再想想看～"))
    else:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="請輸入『選單』來開始遊戲。"))

# ====== 每一題的題目函數（可加圖片）======

def send_question_1(reply_token):
    image = ImageSendMessage(
        original_content_url="https://i.imgur.com/qyCxLdo.jpg",
        preview_image_url="https://i.imgur.com/qyCxLdo.jpg"
    )
    question = TextSendMessage(
        text="第一題：誰是飛天小女警的角色？",
        quick_reply=QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="A 泡泡", text="A")),
            QuickReplyButton(action=MessageAction(label="B 豆豆", text="B")),
            QuickReplyButton(action=MessageAction(label="C 毛毛", text="C")),
        ])
    )
    line_bot_api.reply_message(reply_token, [image, question])

def send_question_2(reply_token):
    image = ImageSendMessage(
        original_content_url="https://i.imgur.com/V8F8j7x.png",
        preview_image_url="https://i.imgur.com/V8F8j7x.png"
    )
    question = TextSendMessage(
        text="第二題：一次函數 y＝－2x－6 通過哪個點？",
        quick_reply=QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="A (-4, 1)", text="A")),
            QuickReplyButton(action=MessageAction(label="B (-4, 2)", text="B")),
            QuickReplyButton(action=MessageAction(label="C (-4, -1)", text="C")),
            QuickReplyButton(action=MessageAction(label="D (-4, -2)", text="D")),
        ])
    )
    line_bot_api.reply_message(reply_token, [image, question])

def send_question_3(reply_token):
    question = TextSendMessage(
        text="第三題：多少個正整數是 18 的倍數，也是 216 的因數？",
        quick_reply=QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="A 2", text="A")),
            QuickReplyButton(action=MessageAction(label="B 6", text="B")),
            QuickReplyButton(action=MessageAction(label="C 10", text="C")),
            QuickReplyButton(action=MessageAction(label="D 12", text="D")),
        ])
    )
    line_bot_api.reply_message(reply_token, question)

def send_question_4(reply_token):
    question = TextSendMessage(
        text="第四題：一份套餐比單點雞排+可樂便宜40元，\n單點雞排送一片+兩杯可樂，比兩份套餐便宜10元。根據敘述，哪個為正確結論？",
        quick_reply=QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="A 套餐140", text="A")),
            QuickReplyButton(action=MessageAction(label="B 套餐120", text="B")),
            QuickReplyButton(action=MessageAction(label="C 雞排90", text="C")),
            QuickReplyButton(action=MessageAction(label="D 雞排70", text="D")),
        ])
    )
    line_bot_api.reply_message(reply_token, question)

# ====== 本地測試啟動 Flask 應用程式 ======
if __name__ == "__main__":
    app.run()
