# Email (SMTP / JavaMail) — what to document

Where to look:
- Mail configuration: `spring.mail.*`, `mail.smtp.*`, JNDI mail sessions — host, port, TLS, sender address (credentials `[REDACTED]`)
- Senders: `JavaMailSender`/`MimeMessageHelper` usage, notification services, templates for message bodies (Thymeleaf/Freemarker/text)
- What triggers mail: jobs, failures, approvals, exports

What to record:
- Every email the application sends: trigger (event, job, failure), recipients (fixed list, configuration key, derived from data), subject, body template, attachments (e.g. Excel exports)
- The conditions under which each email is or is not sent — these are business rules
- Configuration per environment (hosts, sender, recipient lists) and any switch that disables mail
- Retry/failure handling and logging of sent mail
- Tests that cover mail sending and what they need (mock sender, embedded SMTP)
