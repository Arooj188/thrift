import os
import logging
from datetime import datetime
from flask import render_template

try:
    import requests
except ImportError:  # pragma: no cover - requests is expected in production
    requests = None

logger = logging.getLogger(__name__)

RESEND_API_URL = 'https://api.resend.com/emails'


def _get_api_key():
    return os.environ.get('RESEND_API_KEY')


def _get_from_email():
    return os.environ.get('RESEND_FROM_EMAIL', 'onboarding@resend.dev')


def _get_support_email():
    return os.environ.get('SUPPORT_EMAIL', 'thriftsupport@gmail.com')


def send_email(to, subject, html):
    api_key = _get_api_key()
    from_email = _get_from_email()

    if not api_key:
        logger.error('Email sending failed: RESEND_API_KEY is not set.')
        return False

    if requests is None:
        logger.error('Email sending failed: requests library is not available.')
        return False

    payload = {
        'from': from_email,
        'to': [to],
        'subject': subject,
        'html': html,
    }

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=15,
        )

        if response.status_code in (200, 201, 202):
            logger.info('Email sent successfully to %s. Subject: %s', to, subject)
            return True

        logger.error(
            'Email sending failed with status %s. Response: %s',
            response.status_code,
            response.text,
        )
        return False

    except requests.exceptions.Timeout:
        logger.error('Email sending failed: Request timed out.')
        return False
    except requests.exceptions.ConnectionError:
        logger.error('Email sending failed: Network connection failed.')
        return False
    except requests.exceptions.RequestException as e:
        logger.error('Email sending failed: %s', e)
        return False
    except Exception as e:
        logger.error('Email sending failed: Unexpected error: %s', e)
        return False


def send_password_reset_email(email, reset_link):
    support_email = _get_support_email()
    html = render_template(
        'email/reset_password_email.html',
        reset_link=reset_link,
        support_email=support_email,
        year=datetime.utcnow().year,
    )
    subject = 'Reset your Thrift password'
    success = send_email(email, subject, html)

    if success:
        logger.info('Password reset email sent successfully to %s.', email)
    else:
        logger.error('Password reset email failed to send to %s.', email)

    return success
