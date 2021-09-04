FROM python:3.9-slim

ENV PYTHONUNBUFFERED 1
ENV APP gpn_as_notify_receiver
ENV APPDIR /code

RUN mkdir -p $APPDIR
WORKDIR $APPDIR

RUN apt update && apt upgrade -y
RUN apt install libxml2-dev libxslt1-dev

RUN python -m pip install --upgrade pip
ADD . ${APPDIR}/
RUN pip install -r requirements.txt

CMD python main.py