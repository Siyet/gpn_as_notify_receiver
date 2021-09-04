import logging
import os
from datetime import datetime, timedelta

import requests
from exchangelib import DELEGATE, Account, Credentials
from exchangelib.ewsdatetime import EWSDateTime

from pydantic_types import DiscMsg, DiscMsgEmbed, DiscMsgResponse

logger = logging.getLogger(__name__)

DISC_WEBHOOK_URL = os.environ['DISC_WEBHOOK_URL']
DISC_DEV_ROLE = os.environ['DISC_DEV_ROLE']
DT_FORMAT = '%Y-%m-%d %H:%M:%S+00:00'
FREQUENCY_MINUTES = int(os.environ.get('FREQUENCY_MINUTES'))


def sendMsg(title: str, description: str, datetime_received: str):
    resp = requests.post(DISC_WEBHOOK_URL, json=DiscMsg(
        embeds=[DiscMsgEmbed(title=title, description=f'{DISC_DEV_ROLE}\n{description}\n`{datetime_received}`')]
    ).dict(by_alias=True))
    assert resp.status_code == 200, \
        f'Error! Received unexpected HTTP code: {resp.status_code}'
    # resp = DiscMsgResponse(resp.json())
    # TODO: тут можно дописать проверки на соответствие title и description


if __name__ == '__main__':

    mail_account = Account(
        primary_smtp_address=os.environ['MAIL_ADDR'],
        autodiscover=True, access_type=DELEGATE,
        credentials=Credentials(username=os.environ['MAIL_USER'],
                                password=os.environ['MAIL_PASS'])
    )
    folder = mail_account.root / 'Корневой уровень хранилища' / os.environ['MAIL_FOLDER']
    start = EWSDateTime.from_datetime(datetime.now) - timedelta(minutes=FREQUENCY_MINUTES)
    for mail_msg in folder.filter(datetime_received__gt=start).order_by('datetime_received'):
        sendMsg(
            title=mail_msg.subject.strip(),
            description=mail_msg.body.strip(),
            datetime_received=mail_msg.datetime_received
        )
