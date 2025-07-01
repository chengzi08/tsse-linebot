import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction

app = Flask(__name__)

# 從環境變數中取得金鑰
# 部署到 Render 時，我們會把金鑰設定在環境變數中，而不是寫死在程式碼裡
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('Chij1UUyiV9prubdtBD9ijK2LZzAJN2LTjSVP8ldxZGG484Ft0V99Edy41HIETElsCpRV5m5eY+HOAjj770r3W LjtBc3y6Yywi9ke5oavMMTBFPlUyuorobr6mF4d/slO33PxoQk0F3g9HOfhfHrqQdB04t89/1O/w1cDnyilFU=')
LINE_CHANNEL_SECRET = os.environ.get('e237d7487051810e433352655d6dd1ca')

# 確認金鑰是否存在
if LINE_CHANNEL_ACCESS_TOKEN is None or LINE_CHANNEL_SECRET is None:
    print("請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
    # 在本地測試時，如果沒有設定，可以先用下面的假資料，但部署時務必刪除或註解掉
    # LINE_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"
    # LINE_CHANNEL_SECRET = "YOUR_CHANNEL_SECRET"
    # exit() # 部署時建議打開，如果抓不到金鑰就直接停止服務

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 這是接收 LINE Webhook 的主要路徑
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理文字訊息的事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_token = event.reply_token

    # 如果使用者輸入「選單」，就跳出快速回覆選單
    if user_message == "選單":
        # 建立三個按鈕的動作
        action1 = MessageAction(label="毛毛", text="毛毛")
        action2 = MessageAction(label="豆豆", text="豆豆")
        action3 = MessageAction(label="以上皆是", text="以上皆是")
        
        # 建立快速回覆按鈕的列表
        quick_reply_buttons = QuickReply(items=[
            QuickReplyButton(action=action1),
            QuickReplyButton(action=action2),
            QuickReplyButton(action=action3),
        ])

        # 建立要發送的文字訊息，並附加上快速回覆按鈕
        reply_message = TextSendMessage(
            text="有哪些角色呢？",
            quick_reply=quick_reply_buttons
        )
        line_bot_api.reply_message(reply_token, reply_message)
        
    # 處理用戶點擊選項後的回覆
    elif user_message == "毛毛":
        line_bot_api.reply_message(reply_token, TextSendMessage(text="沒錯，她是女同志！"))
    elif user_message == "豆豆":
        line_bot_api.reply_message(reply_token, TextSendMessage(text="是的，她也是一位媽媽！"))
    elif user_message == "以上皆是":
        line_bot_api.reply_message(reply_token, TextSendMessage(text="完全正確！這就是我們想傳達的理念。"))
        
    # Echo Bot: 如果不是以上關鍵字，就回覆一樣的訊息
    else:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=user_message)
        )

# 讓 Gunicorn 可以找到 app 物件
if __name__ == "__main__":
    # 這段是為了方便在本地測試，部署到 Render 時不會執行
    # 你可以在本地終端機執行 python main.py 來啟動測試伺服器
    app.run(port=5001)