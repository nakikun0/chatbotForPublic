from flask import Flask, request, abort, render_template
from dotenv import load_dotenv
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    PushMessageRequest,
    ApiException
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    StickerMessageContent
)
from linebot import LineBotApi
from linebot.models import TextSendMessage
import datetime
import calendar
import time
from testapp.calcNextMonth import calcNextMonth
from sqlalchemy import create_engine, Column, Integer, String, MetaData, Table, \
    inspect, update
from sqlalchemy.sql import insert, select
from sqlalchemy.orm import sessionmaker
import copy

# 初期設定
# ローカル開発環境でのみ dotenv を読み込む
if os.getenv('RENDER') is None:
    from dotenv import load_dotenv
    load_dotenv()
database_url = os.getenv('DATABASE_URL')
access_token = os.getenv('LINE_ACCESS_TOKEN')
webhook_handler = os.getenv('WEBHOOK_HANDLER')
developer_password = os.getenv('PASSWORD_FOR_DEVELOPER')

tokyo_tz = datetime.timezone(datetime.timedelta(hours=9))
dt = datetime.datetime.now(tokyo_tz)  # timezoneの設定

app = Flask(__name__)

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(webhook_handler)  # ←チャンネルシークレット　↑チャンネルトークン
glb_line_bot_api = LineBotApi(access_token)


# データベースへの接続
engine = create_engine(database_url)

# テーブルの定義
metadata = MetaData()

users = Table('users', metadata,
              Column('id', Integer, primary_key=True, autoincrement=True),
              Column('name', String),
              Column('shift', String),
              Column('next_month', String),
              Column('line_id', String),
              )

# テーブルの作成
metadata.create_all(engine)


def sendMessage():
    messages = TextSendMessage(text="本日はバイトがあります!")
    today = str(dt.day)
    print(today)

    Session = sessionmaker(bind=engine)
    session = Session()

    rows = session.query(users).all()
    for row in rows:
        shiftdate = row.shift.split(',')
        print(shiftdate)
        if today in shiftdate:
            glb_line_bot_api.push_message(row.line_id,
                                       messages=messages)


def evening_sendMessage():
    messages = TextSendMessage(text="明日はバイトがあります!")
    nextday = str((dt + datetime.timedelta(days=1)).day)
    print(nextday)

    Session = sessionmaker(bind=engine)
    session = Session()

    rows = session.query(users).all()
    for row in rows:
        shift_date = row.shift.split(',')
        print(shift_date)
        if nextday in shift_date:
            glb_line_bot_api.push_message(row.line_id,
                                       messages=messages)


def change_month():
    Session = sessionmaker(bind=engine)
    session = Session()

    stmt = update(users).values(shift=users.c.next_month)
    session.execute(stmt)
    stmt = update(users).values(next_month=False)
    session.execute(stmt)
    session.commit()


scheduler = BackgroundScheduler()

morning_trigger = CronTrigger(hour=7, minute=0,
                              timezone=timezone('Asia/Tokyo'))
scheduler.add_job(sendMessage, morning_trigger)

evening_trigger = CronTrigger(hour=22, minute=0,
                              timezone=timezone('Asia/Tokyo'))
scheduler.add_job(evening_sendMessage, evening_trigger)

month_trigger = CronTrigger(day=1, hour=6, minute=58,
                            timezone=timezone('Asia/Tokyo'))
scheduler.add_job(change_month, month_trigger)  #月が変わったらシフトデータ更新

scheduler.start()


@app.route("/")
def test():
    return render_template("testapp/index.html")


@app.route("/resister", methods=["GET", "POST"])
def resister():
    weekday, num_days = calendar.monthrange(dt.year, dt.month)
    NextDates = calcNextMonth()
    return render_template("testapp/resister.html", year=dt.year,
                           month=dt.month, days=num_days,
                           next_month=NextDates[0],
                           next_year=NextDates[1], next_days=NextDates[2])


@app.route("/success", methods=["GET", "POST"])
def afterResister():
    # formからデータを取得する
    month_dates_list = request.form.getlist('dates')
    next_datas_list = request.form.getlist('next_dates')
    shift_Datas = ','.join(month_dates_list)
    next_month_Datas = ','.join(next_datas_list)
    name = request.form["username"]

    print(shift_Datas, next_month_Datas)

    Session = sessionmaker(bind=engine)
    session = Session()

    row = session.query(users).filter(users.c.name == name)
    row_first = row.first()

    # 同じ名前のユーザーがいた場合，その行にupdateする
    if row_first:
        stmt = update(users).where(users.c.name == name).values(
            shift=shift_Datas)
        session.execute(stmt)
        stmt = update(users).where(users.c.name == name).values(
            next_month=next_month_Datas)
        session.execute(stmt)
        session.commit()

        return "登録しました，このページは閉じてください"

    else:
        return "正しく登録できませんでした.\nユーザー名に誤りがないか確認してください."


@app.route("/checkDatas", methods=["GET", "POST"])
def check_datas():
    Session = sessionmaker(bind=engine)
    session = Session()
    query = session.query(users)
    results = query.all()

    userdatas = []
    for user in results:
        temp = copy.copy(user)  # tempにcolumnをコピー
        temp = str(temp)  # tempの型がjsonなしで扱えないためstrに変換
        userdatas.append(temp) 
    return render_template("testapp/checkdata.html", password=developer_password, datas=userdatas)


@app.route('/check_shift', methods=["GET", "POST"])
def check_shift():
    Session = sessionmaker(bind=engine)
    session = Session()

    num = 0
    rows = session.query(users).all()
    usersShiftDic = {}
    for row in rows:
        tempName = row.name
        tempThisMonth = row.shift
        tempNextMonth = row.next_month
        shiftDic = {}
        shiftDic["this_month"] = tempThisMonth
        shiftDic["next_month"] = tempNextMonth
        num += 1
        usersShiftDic[tempName] = (copy.copy(shiftDic))  #shiftDic内のデータのコピーを登録
    NextDates = calcNextMonth()
    return render_template('testapp/checkShift.html', usersShift=usersShiftDic,
                           num=num, thisYear=dt.year, thisMonth=dt.month, nextYear=NextDates[0],
                           nextMonth=NextDates[1])

@app.route('/instruction')
def instruction():
    return render_template("testapp/instruction.html")


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info(
            "Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent,
             message=TextMessageContent)  # event.message.textは受け取ったメッセージ
def handle_message(event):
    userId = event.source.user_id

    profile = glb_line_bot_api.get_profile(event.source.user_id)
    name = profile.display_name
    found = False

    Session = sessionmaker(bind=engine)
    session = Session()

    # line_idのみを取得
    rows = session.query(users).filter(users.c.line_id == userId).all()
    for row in rows:
        found = True
    if not found:       #ユーザ情報が登録されていなければ新たに追加
        with engine.connect() as connection:
            trans = connection.begin()
            try:
                # データの挿入
                connection.execute(insert(users), [
                    {'name': name, 'shift': False, 'next_month': False,
                     'line_id': userId},
                ])
                # トランザクションのコミット
                trans.commit()
            except:
                # エラーが発生した場合、トランザクションをロールバック
                trans.rollback()
                raise

    if event.message.text == "ありがとう":
        reply_message = "どういたしまして"

    elif event.message.text == "シフト登録":
        reply_message = "https://linechatbot-5hs4.onrender.com/resister"

    else:
        reply_message = f"こんにちは\nご用件は何ですか?"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_message)]
            )
        )


@handler.add(MessageEvent, message=StickerMessageContent)
def handle_sticker_message(event):
    replymessage = "素敵なスタンプですね！"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=replymessage)]
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
    app.run(DEBUG=True)
