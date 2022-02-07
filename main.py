import logging
import os
import re
from datetime import datetime
from time import sleep

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from exchangelib import DELEGATE, Account, Credentials, Configuration
from xxhash import xxh64
from exchangelib import Q

from pydantic_types import DiscMsg, DiscMsgEmbed, EDiscColors, EStrings

logger = logging.getLogger(__name__)
scheduler = BlockingScheduler()

DISC_WEBHOOK_URL = os.environ['DISC_WEBHOOK_URL']
DISC_DEV_ROLE = os.environ['DISC_DEV_ROLE']
DISC_MSG_LIMIT = int(os.environ.get('DISC_MSG_LIMIT', '1800'))
FREQUENCY_MIN = int(os.environ.get('FREQUENCY_MIN', '10'))
MAIL_USER = os.environ['MAIL_USER']
MAIL_PASS = os.environ['MAIL_PASS']
MAIL_ADDR = os.environ['MAIL_ADDR']
MAIL_FOLDER = os.environ['MAIL_FOLDER'].split(',')
EXCLUDE_MAIL_FROM = os.environ.get('EXCLUDE_MAIL_FROM')
EXCLUDE_MAIL_SUBJECT_CONTAINS = os.environ.get('EXCLUDE_MAIL_SUBJECT_CONTAINS')

re_html_tags = re.compile('(<(/?[^>]+)>)')
re_newline_char = re.compile(r'(?<=\r\n)\r\n')


# TODO:
# 1. использовать faster_than_requests
# 2. авторизовываться не каждый раз, например, раз в час, мб в либе можно определить не протухла ил авторизация
# 3. сохранение сообщений переделать на bulk_update
# 4. попробовать заменить re_newline_char.sub на replace
# 5. вынести в константы внутри треда строковые значения


def send_msg(title: str, description: str):
    if title[:4] == EStrings.OK_TITLE:
        color = EDiscColors.GREEN
    elif title[:9] == EStrings.WARNING_TITLE:
        color = EDiscColors.ORANGE
    else:
        color = EDiscColors.RED
    resp = requests.post(DISC_WEBHOOK_URL, json=DiscMsg(
        embeds=[DiscMsgEmbed(title=title, description=f'{DISC_DEV_ROLE} {description}', color=color)]
    ).dict(by_alias=True))
    assert resp.status_code == 204, \
        f'Error! Received unexpected HTTP code: {resp.status_code}'
    # resp = DiscMsgResponse(resp.json())
    # TODO: тут можно дописать проверки на соответствие title и description


@scheduler.scheduled_job('interval', minutes=10)
def forward_notifications():
    mail_cfg = Configuration(server=EStrings.SERVER,
                             credentials=Credentials(username=MAIL_USER,
                                                     password=MAIL_PASS))
    mail_account = Account(
        primary_smtp_address=MAIL_ADDR,
        autodiscover=False, access_type=DELEGATE,
        config=mail_cfg
    )
    # Просматриваем каждую из указанных папок по очереди
    for folder_ in MAIL_FOLDER:
        folder = mail_account.root / EStrings.ROOT / folder_
        mails = {}
        # Перебираем не прочитанные сообщения и объединяем сообщения с одинаковым заголовком и текстом
        filter_ = folder.filter(is_read=False)
        if EXCLUDE_MAIL_FROM:
            for sender in EXCLUDE_MAIL_FROM.split(EStrings.COMMA):
                filter_ = filter_.filter(subject__not=sender)
        if EXCLUDE_MAIL_SUBJECT_CONTAINS:
            q = Q()
            for exclude_content in EXCLUDE_MAIL_SUBJECT_CONTAINS.split(EStrings.COMMA):
                q &= ~Q(subject__contains=exclude_content)
            filter_ = filter_.filter(q)
        for mail_msg in filter_.order_by(EStrings.DATETIME_RECEIVED):
            subject = mail_msg.subject.strip()
            body = mail_msg.body.strip() if mail_msg.body else EStrings.EMPTY
            if EStrings.HTML_TAG in body:
                # Удаляем атрибут style из всех тегов
                body = re_html_tags.sub(EStrings.EMPTY, body.split(EStrings.STYLE_CLOSE_TAG)[-1])
                body = re_newline_char.sub(EStrings.EMPTY, body)
            if len(body) > DISC_MSG_LIMIT:
                # Учитываем ограничение discord'a по длине сообщения
                body = body[:DISC_MSG_LIMIT] + EStrings.THREE_DOTS
            key = xxh64(subject + body).hexdigest()
            if key not in mails:
                mails[key] = {
                    EStrings.SUBJECT: subject,
                    EStrings.BODY: body,
                    EStrings.START: None,
                    EStrings.END: None,
                    EStrings.COUNT: 0,
                    EStrings.MESSAGES: []
                }
            if not mails[key][EStrings.START] or mail_msg.datetime_received < mails[key][EStrings.START]:
                mails[key][EStrings.START] = mail_msg.datetime_received
            if not mails[key][EStrings.END] or mail_msg.datetime_received > mails[key][EStrings.END]:
                mails[key][EStrings.END] = mail_msg.datetime_received
            mails[key][EStrings.COUNT] += 1
            mails[key][EStrings.MESSAGES].append(mail_msg)

        # Сообщения с одинаковым заголовком, компануем в отдельное сообщение в discord, но не более 1800 символов
        # в одном сообщении. Исходные сообщения длиннее 1800 символов обрезаются
        disc_messages = {}
        for mail in mails.values():
            title = mail[EStrings.SUBJECT]
            datetime_received = str(mail[EStrings.START]).replace(EStrings.UTC_TIME_INCREASE, EStrings.UTC)
            end = str(mail[EStrings.END]).replace(EStrings.UTC_TIME_INCREASE, EStrings.UTC)
            if end != datetime_received:
                datetime_received += f' - {end}'
            if mail[EStrings.COUNT] > 1:
                datetime_received += f' (x{mail[EStrings.COUNT]})'
            description = f'{datetime_received}:\n```{mail[EStrings.BODY]}```'
            if title not in disc_messages:
                disc_messages[title] = {
                    EStrings.DESCRIPTIONS: [description],
                    EStrings.MESSAGES: mail[EStrings.MESSAGES]
                }
            else:
                if len(disc_messages[title][EStrings.DESCRIPTIONS][-1] + mail[EStrings.BODY]) > DISC_MSG_LIMIT:
                    disc_messages[title][EStrings.DESCRIPTIONS].append(description)
                else:
                    disc_messages[title][EStrings.DESCRIPTIONS][-1] += '\n\n' + description
                disc_messages[title][EStrings.MESSAGES] += mail[EStrings.MESSAGES]

        for title in disc_messages:
            for description in disc_messages[title][EStrings.DESCRIPTIONS]:
                send_msg(title=title, description=description)
                sleep(1)  # чтобы не отхватить 429 от discord
            for mail_msg in disc_messages[title][EStrings.MESSAGES]:
                mail_msg.is_read = True
                mail_msg.save()  # TODO: переделать на bulk_update
    now = str(datetime.utcnow())[:-3].replace(EStrings.SPACE, EStrings.T) + EStrings.Z
    logger.info(f'[{now}] the transfer was completed successfully.')


forward_notifications()
scheduler.start()
