import logging
import os
import re
from datetime import datetime
from time import sleep

import requests
from exchangelib import DELEGATE, Account, Credentials, Configuration, FaultTolerance
from xxhash import xxh64
from exchangelib import Q

from pydantic_types import DiscMsg, DiscMsgEmbed, EDiscColors

logger = logging.getLogger(__name__)

DISC_WEBHOOK_URL = os.environ['DISC_WEBHOOK_URL']
DISC_DEV_ROLE = os.environ.get('DISC_DEV_ROLE', '')
DISC_MSG_LIMIT = int(os.environ.get('DISC_MSG_LIMIT', '1800'))
MAIL_USER = os.environ['MAIL_USER']
MAIL_PASS = os.environ['MAIL_PASS']
MAIL_ADDR = os.environ['MAIL_ADDR']
MAIL_FOLDER = os.environ['MAIL_FOLDER'].split(',')
EXCLUDE_MAIL_FROM = os.environ.get('EXCLUDE_MAIL_FROM')
EXCLUDE_MAIL_SUBJECT_CONTAINS = os.environ.get('EXCLUDE_MAIL_SUBJECT_CONTAINS')
MAIL_HOST = os.environ.get('MAIL_HOST', 'mail.gazprom-neft.ru')
ROOT_FOLDER = os.environ.get('ROOT_FOLDER', 'Корневой уровень хранилища')

OK_TITLE_START, WARNING_TITLE_START = '[OK]', '[Warning]'
COMMA_CHAR, EMPTY_CHAR, SPACE_CHAR = ',', '', ' '
START, END = 'start', 'end'
DESCRIPTIONS = 'descriptions'
MESSAGES = 'messages'
COUNT = 'count'
BODY, SUBJECT = 'body', 'subject'
UTC = ' (UTC)'
UTC_TIME_INCREASE = '+00:00'
STYLE_CLOSE_TAG, HTML_TAG = '</style>', '<html'
THREE_DOTS = '...'
IS_READ = 'is_read'
DATETIME_RECEIVED = 'datetime_received'
T_CHAR, Z_CHAR = 'T', 'Z'
RETURN_CHAR = '\n\n'
WIN_RETURN_CHAR, WIN_DBL_RETURN_CHAR = '\r\n', '\r\n\r\n'
RE_HTML_TAGS = re.compile('(<(/?[^>]+)>)')
MAIL_CFG = Configuration(retry_policy=FaultTolerance(max_wait=3600), server=MAIL_HOST,
                         credentials=Credentials(username=MAIL_USER, password=MAIL_PASS))


# TODO:
# 1. использовать faster_than_requests


def send_msg(title: str, description: str):
    if title[:4] == OK_TITLE_START:
        color = EDiscColors.GREEN
    elif title[:9] == WARNING_TITLE_START:
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


def handler(event, context):
    mail_account = Account(primary_smtp_address=MAIL_ADDR, autodiscover=False, access_type=DELEGATE, config=MAIL_CFG)
    # Просматриваем каждую из указанных папок по очереди
    for folder_ in MAIL_FOLDER:
        folder = mail_account.root / ROOT_FOLDER / folder_
        mails = {}
        # Перебираем не прочитанные сообщения и объединяем сообщения с одинаковым заголовком и текстом
        filter_ = folder.filter(is_read=False)
        if EXCLUDE_MAIL_FROM:
            for sender in EXCLUDE_MAIL_FROM.split(COMMA_CHAR):
                filter_ = filter_.filter(subject__not=sender)
        if EXCLUDE_MAIL_SUBJECT_CONTAINS:
            q = Q()
            for exclude_content in EXCLUDE_MAIL_SUBJECT_CONTAINS.split(COMMA_CHAR):
                q &= ~Q(subject__contains=exclude_content)
            filter_ = filter_.filter(q)
        for mail_msg in filter_.order_by(DATETIME_RECEIVED):
            subject = mail_msg.subject.strip()
            body = mail_msg.body.strip() if mail_msg.body else EMPTY_CHAR
            if HTML_TAG in body:
                # Удаляем атрибут style из всех тегов
                body = RE_HTML_TAGS.sub(EMPTY_CHAR, body.split(STYLE_CLOSE_TAG)[-1])
                while WIN_DBL_RETURN_CHAR in body:
                    body = body.replace(WIN_DBL_RETURN_CHAR, WIN_RETURN_CHAR)
            if len(body) > DISC_MSG_LIMIT:
                # Учитываем ограничение discord'a по длине сообщения
                body = body[:DISC_MSG_LIMIT] + THREE_DOTS
            key = xxh64(subject + body).hexdigest()
            if key not in mails:
                mails[key] = {
                    SUBJECT: subject,
                    BODY: body,
                    START: None,
                    END: None,
                    COUNT: 0,
                    MESSAGES: []
                }
            if not mails[key][START] or mail_msg.datetime_received < mails[key][START]:
                mails[key][START] = mail_msg.datetime_received
            if not mails[key][END] or mail_msg.datetime_received > mails[key][END]:
                mails[key][END] = mail_msg.datetime_received
            mails[key][COUNT] += 1
            mails[key][MESSAGES].append(mail_msg)

        # Сообщения с одинаковым заголовком, компануем в отдельное сообщение в discord, но не более 1800 символов
        # в одном сообщении. Исходные сообщения длиннее 1800 символов обрезаются
        disc_messages = {}
        for mail in mails.values():
            title = mail[SUBJECT]
            datetime_received = str(mail[START]).replace(UTC_TIME_INCREASE, UTC)
            end = str(mail[END]).replace(UTC_TIME_INCREASE, UTC)
            if end != datetime_received:
                datetime_received += f' - {end}'
            if mail[COUNT] > 1:
                datetime_received += f' (x{mail[COUNT]})'
            description = f'{datetime_received}:\n```{mail[BODY]}```'
            if title not in disc_messages:
                disc_messages[title] = {
                    DESCRIPTIONS: [description],
                    MESSAGES: mail[MESSAGES]
                }
            else:
                if len(disc_messages[title][DESCRIPTIONS][-1] + mail[BODY]) > DISC_MSG_LIMIT:
                    disc_messages[title][DESCRIPTIONS].append(description)
                else:
                    disc_messages[title][DESCRIPTIONS][-1] += RETURN_CHAR + description
                disc_messages[title][MESSAGES] += mail[MESSAGES]

        for title in disc_messages:
            for description in disc_messages[title][DESCRIPTIONS]:
                send_msg(title=title, description=description)
                sleep(1)  # чтобы не отхватить 429 от discord
            for mail_msg in disc_messages[title][MESSAGES]:
                mail_msg.is_read = True
            mail_account.bulk_update([(msg, (IS_READ,)) for msg in disc_messages[title][MESSAGES]])
    now = str(datetime.utcnow())[:-3].replace(SPACE_CHAR, T_CHAR) + Z_CHAR
    return {'statusCode': 200, 'body': f'[{now}] the transfer was completed successfully.'}


if __name__ == '__main__':
    handler(None, None)
