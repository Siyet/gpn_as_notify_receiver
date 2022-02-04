import os
from enum import IntEnum
from typing import List, Optional

from pydantic.fields import Field
from pydantic.main import BaseModel

DISC_WEBHOOK_ID = os.environ['DISC_WEBHOOK_ID']


class EDiscColors(IntEnum):
    WHITE = 16777215
    BLURPLE = 5793266
    GREYPLE = 10070709
    DARK_BUT_NOT_BLACK = 2895667
    NOT_QUITE_BLACK = 2303786
    GREEN = 5763719
    YELLOW = 16705372
    FUSCHIA = 15418782
    RED = 15548997
    BLACK = 2303786
    ORANGE = 15105570


class DiscMsgEmbed(BaseModel):
    type_ = Field(alias='type', default='rich')
    title: str
    description: str
    color: EDiscColors = EDiscColors.RED


class DiscMsg(BaseModel):
    content: Optional[str]
    embeds: List[DiscMsgEmbed]


class DiscAuthor(BaseModel):
    bot = True
    id = DISC_WEBHOOK_ID
    username: str
    avatar: str
    discriminator: str


class DiscMsgResponse(BaseModel):
    id: str
    type_ = Field(alias='type', default=0)
    content: str
    channel_id: str
    author: DiscAuthor
    attachments = []
    embeds: List[DiscMsgEmbed]
    mentions = []
    mention_roles = []
    pinned = False
    mention_everyone = False
    tts = False
    timestamp: str
    edited_timestamp: Optional[str]
    flags = 0
    components = []
    webhook_id = DISC_WEBHOOK_ID
