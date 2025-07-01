import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage
)

app = Flask(__name__)

# 從環境變數中取得金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

if LINE_CHANNEL_ACCESS_TOKEN is None or LINE_CHANNEL_SECRET is None:
    print("請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
    # exit()  # 部署時建議打開

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
    user_message = event.message.text.strip()
    reply_token = event.reply_token

    # 首次進入遊戲
    if user_message == "選單":
        flex_menu = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "歡迎來到問答遊戲，請點選開始！",
                        "weight": "bold",
                        "size": "md",
                        "margin": "md"
                    },
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#6EC1E4",
                        "action": {
                            "type": "message",
                            "label": "開始遊戲",
                            "text": "開始遊戲"
                        }
                    }
                ]
            }
        }
        line_bot_api.reply_message(
            reply_token,
            FlexSendMessage(alt_text="歡迎來到問答遊戲，請點選開始！", contents=flex_menu)
        )
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
            send_question_1(reply_token)
    elif progress == 2:
        if user_message == "C":
            user_progress[user_id] = 3
            send_question_3(reply_token)
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="錯誤答案！重來看看～"))
            send_question_2(reply_token)
    elif progress == 3:
        if user_message == "B":
            user_progress[user_id] = 4
            send_question_4(reply_token)
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="這不是正確答案喔～再試一次！"))
            send_question_3(reply_token)
    elif progress == 4:
        if user_message == "B":
            line_bot_api.reply_message(reply_token, TextSendMessage(text="🎉 恭喜你全部答對！你完成了通關～🎊"))
            user_progress[user_id] = 0  # 重置遊戲
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="最後一題答錯了，再想想看～"))
            send_question_4(reply_token)
    else:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="請輸入『選單』來開始遊戲。"))

# ====== 每一題的 Flex Message 按鈕題目 ======

def send_question_1(reply_token):
    flex_message = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://github.com/chengzi08/tsse-linebot/blob/main/Q1.png?raw=true",
            "size": "full",
            "aspectRatio": "1.51:1",
            "aspectMode": "fit"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "第一題：誰是飛天小女警的角色？",
                    "weight": "bold",
                    "size": "md",
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#6EC1E4",
                            "action": {
                                "type": "message",
                                "label": "A 泡泡",
                                "text": "A"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#A3D977",
                            "action": {
                                "type": "message",
                                "label": "B 豆豆",
                                "text": "B"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#F7B2B7",
                            "action": {
                                "type": "message",
                                "label": "C 毛毛",
                                "text": "C"
                            }
                        }
                    ]
                }
            ]
        }
    }
    line_bot_api.reply_message(
        reply_token,
        FlexSendMessage(alt_text="第一題", contents=flex_message)
    )

def send_question_2(reply_token):
    flex_message = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://github.com/chengzi08/tsse-linebot/blob/main/Q2.png?raw=true",
            "size": "full",
            "aspectRatio": "1.51:1",
            "aspectMode": "fit"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "第二題：一次函數 y＝－2x－6 通過哪個點？",
                    "weight": "bold",
                    "size": "md",
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#6EC1E4",
                            "action": {
                                "type": "message",
                                "label": "A (-4, 1)",
                                "text": "A"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#A3D977",
                            "action": {
                                "type": "message",
                                "label": "B (-4, 2)",
                                "text": "B"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#F7B2B7",
                            "action": {
                                "type": "message",
                                "label": "C (-4, -1)",
                                "text": "C"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#FFD966",
                            "action": {
                                "type": "message",
                                "label": "D (-4, -2)",
                                "text": "D"
                            }
                        }
                    ]
                }
            ]
        }
    }
    line_bot_api.reply_message(
        reply_token,
        FlexSendMessage(alt_text="第二題", contents=flex_message)
    )

def send_question_3(reply_token):
    flex_message = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "第三題：多少個正整數是 18 的倍數，也是 216 的因數？",
                    "weight": "bold",
                    "size": "md",
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#6EC1E4",
                            "action": {
                                "type": "message",
                                "label": "A 2",
                                "text": "A"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#A3D977",
                            "action": {
                                "type": "message",
                                "label": "B 6",
                                "text": "B"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#F7B2B7",
                            "action": {
                                "type": "message",
                                "label": "C 10",
                                "text": "C"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#FFD966",
                            "action": {
                                "type": "message",
                                "label": "D 12",
                                "text": "D"
                            }
                        }
                    ]
                }
            ]
        }
    }
    line_bot_api.reply_message(
        reply_token,
        FlexSendMessage(alt_text="第三題", contents=flex_message)
    )

def send_question_4(reply_token):
    flex_message = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "第四題：一份套餐比單點雞排+可樂便宜40元，\n單點雞排送一片+兩杯可樂，比兩份套餐便宜10元。\n根據敘述，哪個為正確結論？",
                    "weight": "bold",
                    "size": "md",
                    "margin": "md",
                    "wrap": True
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#6EC1E4",
                            "action": {
                                "type": "message",
                                "label": "A 套餐140",
                                "text": "A"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#A3D977",
                            "action": {
                                "type": "message",
                                "label": "B 套餐120",
                                "text": "B"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#F7B2B7",
                            "action": {
                                "type": "message",
                                "label": "C 雞排90",
                                "text": "C"
                            }
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#FFD966",
                            "action": {
                                "type": "message",
                                "label": "D 雞排70",
                                "text": "D"
                            }
                        }
                    ]
                }
            ]
        }
    }
    line_bot_api.reply_message(
        reply_token,
        FlexSendMessage(alt_text="第四題", contents=flex_message)
    )

# ====== 本地測試啟動 Flask 應用程式 ======
if __name__ == "__main__":
    app.run()
