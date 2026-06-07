"""
pgappforge/plugins/erp/platform/email/sender.py

EmailSender — stdlib SMTP email dispatch. No external dependencies.

Config keys (all optional; log-only mode when absent):
  SMTP_HOST: str  (default: localhost)
  SMTP_PORT: int  (default: 587)
  SMTP_USER: str
  SMTP_PASSWORD: str
  SMTP_FROM: str  (default: noreply@app.local)
  SMTP_TLS: bool  (default: True)
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

log = logging.getLogger(__name__)


class EmailSendError(Exception):
	pass


class EmailSender:
	def send(
		self,
		to: str,
		subject: str,
		body_text: str,
		session: Any = None,
		*,
		body_html: str | None = None,
		from_addr: str | None = None,
	) -> bool:
		"""Send email via SMTP. Returns True on success, False if config absent (log-only fallback).

		Raises EmailSendError on SMTP failure when config IS present.
		"""
		try:
			from flask import current_app
			host = current_app.config.get("SMTP_HOST", "")
			port = int(current_app.config.get("SMTP_PORT", 587))
			user = current_app.config.get("SMTP_USER", "")
			password = current_app.config.get("SMTP_PASSWORD", "")
			from_a = from_addr or current_app.config.get("SMTP_FROM", "noreply@app.local")
			use_tls = current_app.config.get("SMTP_TLS", True)
		except (RuntimeError, AttributeError):
			log.info(
				"EmailSender: no Flask context — email to %s logged only (subject: %s)",
				to, subject,
			)
			return False
		if not host:
			log.info("EmailSender: SMTP_HOST not configured — email to %s logged only", to)
			return False
		msg = MIMEMultipart("alternative")
		msg["Subject"] = subject
		msg["From"] = from_a
		msg["To"] = to
		msg.attach(MIMEText(body_text, "plain", "utf-8"))
		if body_html:
			msg.attach(MIMEText(body_html, "html", "utf-8"))
		try:
			smtp = smtplib.SMTP(host, port, timeout=10)
			if use_tls:
				smtp.starttls()
			if user and password:
				smtp.login(user, password)
			smtp.sendmail(from_a, [to], msg.as_string())
			smtp.quit()
			log.info("EmailSender: sent to %s subject=%r", to, subject)
			return True
		except Exception as exc:
			raise EmailSendError(f"SMTP error sending to {to}: {exc}") from exc


__all__ = ["EmailSender", "EmailSendError"]
