import logging
import os
from datetime import datetime
from time import sleep

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from exchangelib import DELEGATE, Account, Credentials, Configuration
from xxhash import xxh64

from pydantic_types import DiscMsg, DiscMsgEmbed

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


def send_msg(title: str, description: str):
    resp = requests.post(DISC_WEBHOOK_URL, json=DiscMsg(
        embeds=[DiscMsgEmbed(title=title, description=f'{DISC_DEV_ROLE} {description}')]
    ).dict(by_alias=True))
    assert resp.status_code == 204, \
        f'Error! Received unexpected HTTP code: {resp.status_code}'
    # resp = DiscMsgResponse(resp.json())
    # TODO: тут можно дописать проверки на соответствие title и description


@scheduler.scheduled_job('interval', minutes=10)
def forward_notifications():
    mail_cfg = Configuration(server='mail.gazprom-neft.ru',
                             credentials=Credentials(username=MAIL_USER,
                                                     password=MAIL_PASS))
    mail_account = Account(
        primary_smtp_address=MAIL_ADDR,
        autodiscover=False, access_type=DELEGATE,
        config=mail_cfg
    )
    # Просматриваем каждую из указанных папок по очереди
    for folder_ in MAIL_FOLDER:
        folder = mail_account.root / 'Корневой уровень хранилища' / folder_
        mails = {}
        # Перебираем не прочитанные сообщения и объединяем сообщения с одинаковым заголовком и текстом
        for mail_msg in folder.filter(is_read=False).order_by('datetime_received'):
            subject = mail_msg.subject.strip()
            body = mail_msg.body.strip() if mail_msg.body else ''
            if len(body) > DISC_MSG_LIMIT:
                # Учитываем ограничение discord'a по длине сообщения
                body = body[:DISC_MSG_LIMIT] + '...'
            key = xxh64(subject + body).hexdigest()
            if key not in mails:
                mails[key] = {
                    'subject': subject,
                    'body': body,
                    'start': None,
                    'end': None,
                    'count': 0,
                    'messages': []
                }
            if not mails[key]['start'] or mail_msg.datetime_received < mails[key]['start']:
                mails[key]['start'] = mail_msg.datetime_received
            if not mails[key]['end'] or mail_msg.datetime_received > mails[key]['end']:
                mails[key]['end'] = mail_msg.datetime_received
            mails[key]['count'] += 1
            mails[key]['messages'].append(mail_msg)

        # Сообщения с одинаковым заголовком, компануем в отдельное сообщение в discord, но не более 1800 символов
        # в одном сообщении. Исходные сообщения длиннее 1800 символов обрезаются
        disc_messages = {}
        for mail in mails.values():
            title = mail['subject']
            datetime_received = str(mail['start']).replace('+00:00', 'Z').replace(' ', 'T')
            end = str(mail['end']).replace('+00:00', ' (UTC)')
            if end != datetime_received:
                datetime_received += f' - {end}'
            if mail['count'] > 1:
                datetime_received += f' (x{mail["count"]})'
            description = f'**{datetime_received}**:\n```{mail["body"]}```'
            if title not in disc_messages:
                disc_messages[title] = {
                    'descriptions': [description],
                    'messages': mail['messages']
                }
            else:
                if len(disc_messages[title]['descriptions'][-1] + mail['body']) > DISC_MSG_LIMIT:
                    disc_messages[title]['descriptions'].append(description)
                else:
                    disc_messages[title]['descriptions'][-1] += '\n\n' + description
                disc_messages[title] += mail['messages']

        for title in disc_messages:
            for description in disc_messages[title]['descriptions']:
                send_msg(title=title, description=description)
                sleep(1)  # чтобы не отхватить 429 от discord
            for mail_msg in disc_messages[title]['messages']:
                mail_msg.is_read = True
                mail_msg.save()  # TODO: переделать на bulk_update
    now = str(datetime.utcnow())[:-3].replace(' ', 'T') + 'Z'
    logger.info(f'[{now}] the transfer was completed successfully.')


forward_notifications()
scheduler.start()
