from threading import Thread

from flask import current_app, render_template
from flask_mail import Message
import os

from . import mail


def send_async_email(app, msg):
    with app.app_context():
        mail.send(msg)


def send_email(to, subject, template, **kwargs):
    app = current_app._get_current_object()
    msg = Message(app.config['FLASKY_MAIL_SUBJECT_PREFIX'] + ' ' + subject,
                  sender=app.config['FLASKY_MAIL_SENDER'], recipients=[to])
    msg.body = render_template(template + '.txt', **kwargs)
    msg.html = render_template(template + '.html', **kwargs)
    thr = Thread(target=send_async_email, args=[app, msg])
    thr.start()
    return thr


def email_me(name, subject, email, message):

    msg = Message(subject, sender=email, recipients=[ os.environ.get('FLASKY_ADMIN')])
    msg.body = """ 
    From: %s @ %s;
    %s
    """ % (name, email, message)
    mail.send(msg)
