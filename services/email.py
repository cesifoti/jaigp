"""Email service for sending verification emails."""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import config


class EmailService:
    """Service for sending emails."""

    def __init__(self):
        self.smtp_host = config.SMTP_HOST
        self.smtp_port = config.SMTP_PORT
        self.smtp_user = config.SMTP_USER
        self.smtp_password = config.SMTP_PASSWORD
        self.from_email = config.SMTP_FROM_EMAIL
        self.from_name = config.SMTP_FROM_NAME

    def send_verification_email(self, to_email: str, verification_url: str, paper_title: str) -> bool:
        """Send paper submission verification email.

        Args:
            to_email: Recipient email address
            verification_url: Full URL for verification
            paper_title: Title of the submitted paper

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"Verify Your JAIGP Paper Submission: {paper_title}"
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email

            # Plain text version
            text_content = f"""
Hello,

Thank you for submitting your paper to JAIGP (Journal for AI Generated Papers).

Paper Title: {paper_title}

To complete your submission and make your paper publicly visible, please verify your email address by clicking the link below:

{verification_url}

This link will expire in 7 days.

If you did not submit this paper, please ignore this email.

Best regards,
JAIGP Team
https://jaigp.org
"""

            # HTML version
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #334155; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #2563eb; color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px; }}
        .button {{ display: inline-block; padding: 12px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; }}
        .paper-title {{ background: #f1f5f9; padding: 15px; border-left: 4px solid #2563eb; margin: 20px 0; }}
        .footer {{ text-align: center; margin-top: 30px; color: #64748b; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">JAIGP</h1>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">Journal for AI Generated Papers</p>
        </div>
        <div class="content">
            <h2 style="color: #1e293b; margin-top: 0;">Verify Your Paper Submission</h2>
            <p>Thank you for submitting your paper to JAIGP!</p>

            <div class="paper-title">
                <strong>Paper Title:</strong><br>
                {paper_title}
            </div>

            <p>To complete your submission and make your paper publicly visible, please verify your email address:</p>

            <p style="text-align: center; margin: 30px 0;">
                <a href="{verification_url}" class="button">Verify Email Address</a>
            </p>

            <p style="font-size: 14px; color: #64748b;">
                Or copy and paste this link into your browser:<br>
                <a href="{verification_url}" style="color: #2563eb; word-break: break-all;">{verification_url}</a>
            </p>

            <p style="font-size: 14px; color: #64748b; margin-top: 30px;">
                This link will expire in 7 days. If you did not submit this paper, please ignore this email.
            </p>
        </div>
        <div class="footer">
            <p>JAIGP - Journal for AI Generated Papers<br>
            <a href="https://jaigp.org" style="color: #2563eb;">https://jaigp.org</a></p>
        </div>
    </div>
</body>
</html>
"""

            # Attach parts
            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            # Send email
            if not self.smtp_user or not self.smtp_password:
                print("WARNING: SMTP credentials not configured. Email would be sent to:", to_email)
                print("Verification URL:", verification_url)
                return True  # In dev mode, just log it

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            print(f"✓ Verification email sent to {to_email}")
            return True

        except Exception as e:
            print(f"ERROR: Failed to send verification email: {e}")
            return False

    def _send_email(self, to_email: str, subject: str, text_content: str, html_content: str) -> bool:
        """Generic email sending helper."""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email

            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            if not self.smtp_user or not self.smtp_password:
                print(f"WARNING: SMTP credentials not configured. Email would be sent to: {to_email}")
                print(f"Subject: {subject}")
                return True

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            print(f"Email sent to {to_email}: {subject}")
            return True

        except Exception as e:
            print(f"ERROR: Failed to send email to {to_email}: {e}")
            return False

    def _email_wrapper(self, body_html: str, body_text: str) -> str:
        """Wrap HTML body content in the standard JAIGP email template."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #334155; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #2563eb; color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px; }}
        .button {{ display: inline-block; padding: 12px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; }}
        .button-green {{ display: inline-block; padding: 12px 24px; background: #10b981; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; }}
        .highlight {{ background: #f1f5f9; padding: 15px; border-left: 4px solid #2563eb; margin: 20px 0; }}
        .footer {{ text-align: center; margin-top: 30px; color: #64748b; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">JAIGP</h1>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">Journal for AI Generated Papers</p>
        </div>
        <div class="content">
            {body_html}
        </div>
        <div class="footer">
            <p>JAIGP - Journal for AI Generated Papers<br>
            <a href="https://jaigp.org" style="color: #2563eb;">https://jaigp.org</a></p>
        </div>
    </div>
</body>
</html>"""

    def send_nudge_verification(self, to_email: str, paper_title: str, verification_url: str) -> bool:
        """Send a polite reminder to verify a paper submission."""
        subject = f"Reminder: Please Verify Your JAIGP Submission — {paper_title}"

        text_content = f"""Hello,

This is a friendly reminder that your paper submission to JAIGP is still awaiting email verification.

Paper Title: {paper_title}

To complete your submission and make your paper publicly visible, please click the link below:

{verification_url}

If you've already verified this paper, please disregard this message.

If you have any questions or need assistance, feel free to reply to this email.

Best regards,
JAIGP Editorial Team
https://jaigp.org"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Verification Reminder</h2>
            <p>Hello,</p>
            <p>This is a friendly reminder that your paper submission to JAIGP is still awaiting email verification.</p>
            <div class="highlight">
                <strong>Paper Title:</strong><br>{paper_title}
            </div>
            <p>To complete your submission and make your paper publicly visible, please click the button below:</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{verification_url}" class="button">Verify &amp; Continue Submission</a>
            </p>
            <p style="font-size: 14px; color: #64748b;">
                Or copy and paste this link into your browser:<br>
                <a href="{verification_url}" style="color: #2563eb; word-break: break-all;">{verification_url}</a>
            </p>
            <p style="font-size: 14px; color: #64748b;">
                If you've already verified this paper, please disregard this message.
                If you have any questions, feel free to reply to this email.
            </p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_endorsement_notification(self, to_email: str, paper_title: str, endorser_name: str, paper_url: str) -> bool:
        """Notify paper authors that their paper was endorsed."""
        subject = f"Your JAIGP Paper Has Been Endorsed: {paper_title}"

        text_content = f"""Your paper "{paper_title}" has been endorsed by {endorser_name}.

This endorsement advances your paper to Stage 2 (Endorsed) in the review pipeline.

View your paper: https://jaigp.org{paper_url}

Best regards,
JAIGP Team"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Paper Endorsed!</h2>
            <p>Great news! Your paper has been endorsed by <strong>{endorser_name}</strong>.</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>This endorsement advances your paper to <strong>Stage 2 (Endorsed)</strong> in the review pipeline.</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="https://jaigp.org{paper_url}" class="button-green">View Paper</a>
            </p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_review_invitation(self, to_email: str, reviewer_name: str, paper_title: str, invitation_url: str, reviewer_type: str) -> bool:
        """Invite a reviewer to review a paper."""
        type_desc = "author-suggested reviewer" if reviewer_type == "author_suggested" else "reference-cited reviewer"
        subject = f"JAIGP Review Invitation: {paper_title}"

        text_content = f"""Dear {reviewer_name},

You have been invited as a {type_desc} for the paper:

"{paper_title}"

To review this paper, please visit: {invitation_url}

You will need to authenticate with ORCID to submit your review.

If you wish to decline, you can do so at the same link without logging in.

Best regards,
JAIGP Editorial Team"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Review Invitation</h2>
            <p>Dear {reviewer_name},</p>
            <p>You have been invited as a <strong>{type_desc}</strong> for the following paper:</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>You will need to authenticate with <strong>ORCID</strong> to submit your review, ensuring verified reviewer identities.</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{invitation_url}" class="button">Review Paper</a>
            </p>
            <p style="font-size: 14px; color: #64748b;">
                If you wish to decline this invitation, you can do so at the same link without logging in.
            </p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_review_received(self, to_email: str, paper_title: str, reviewer_name: str) -> bool:
        """Notify author that a review was submitted."""
        subject = f"Review Received for Your Paper: {paper_title}"

        text_content = f"""A review has been submitted for your paper "{paper_title}" by {reviewer_name}.

View your paper to see the review: https://jaigp.org

Best regards,
JAIGP Team"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Review Received</h2>
            <p>A review has been submitted for your paper by <strong>{reviewer_name}</strong>.</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>You can view the full review on your paper's page.</p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_editorial_decision(self, to_email: str, paper_title: str, decision: str, reasoning: str) -> bool:
        """Notify author of editorial decision."""
        decision_text = {"accept": "Accepted", "reject": "Rejected", "revisions_needed": "Revisions Needed"}.get(decision, decision)
        subject = f"Editorial Decision for Your Paper: {paper_title}"

        text_content = f"""An editorial decision has been made for your paper "{paper_title}".

Decision: {decision_text}

{f'Reasoning: {reasoning}' if reasoning else ''}

Best regards,
JAIGP Editorial Team"""

        color = "#10b981" if decision == "accept" else "#ef4444" if decision == "reject" else "#f59e0b"
        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Editorial Decision</h2>
            <p>An editorial decision has been made for your paper:</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p style="font-size: 18px; font-weight: bold; color: {color};">{decision_text}</p>
            {f'<p><strong>Reasoning:</strong> {reasoning}</p>' if reasoning else ''}"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_staleness_warning(self, to_email: str, paper_title: str, days_remaining: int, paper_url: str) -> bool:
        """Warn author about approaching stage deadline."""
        subject = f"Deadline Approaching: {paper_title} ({days_remaining} days remaining)"

        text_content = f"""Your paper "{paper_title}" has {days_remaining} days remaining in its current review stage.

Please take action to advance your paper before the deadline.

You can request a 20-day extension if you need more time.

View your paper: https://jaigp.org{paper_url}

Best regards,
JAIGP Team"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Deadline Approaching</h2>
            <p>Your paper has <strong style="color: #ef4444;">{days_remaining} days remaining</strong> in its current review stage.</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>Please take action to advance your paper before the deadline. You can also request a 20-day extension if needed.</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="https://jaigp.org{paper_url}" class="button">View Paper</a>
            </p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_extension_decision(self, to_email: str, paper_title: str, approved: bool, paper_url: str) -> bool:
        """Notify author of extension request decision."""
        status = "Approved" if approved else "Denied"
        subject = f"Extension Request {status}: {paper_title}"

        text_content = f"""Your extension request for "{paper_title}" has been {status.lower()}.

{'Your deadline has been extended by 20 days.' if approved else 'Please take action to advance your paper.'}

View your paper: https://jaigp.org{paper_url}

Best regards,
JAIGP Team"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Extension Request {status}</h2>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>{'Your deadline has been extended by 20 days.' if approved else 'Your extension request was denied. Please take action to advance your paper.'}</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="https://jaigp.org{paper_url}" class="button">View Paper</a>
            </p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_screening_pass(self, to_email: str, paper_title: str, paper_url: str) -> bool:
        """Notify author that their paper passed AI screening and is now live."""
        subject = f"Your Paper Has Passed AI Screening: {paper_title}"

        text_content = f"""Congratulations!

Your paper has passed our AI quality screening and is now live on JAIGP at Stage 1 (AI Screened).

Paper: {paper_title}

It is now publicly visible and eligible for endorsement from bronze+ scholars, which will advance it to the next stage of the review pipeline.

View your paper: https://jaigp.org{paper_url}

Best regards,
JAIGP Team"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Paper Passed AI Screening!</h2>
            <p>Congratulations! Your paper has passed our AI quality screening and is now live on JAIGP.</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>Your paper is now at <strong>Stage 1: AI Screened</strong> and is publicly visible. It is eligible for endorsement from bronze+ scholars to advance further in the review pipeline.</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="https://jaigp.org{paper_url}" class="button-green">View Your Paper</a>
            </p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_borderline_rejection(self, to_email: str, paper_title: str, streak: int) -> bool:
        """Soft rejection for borderline papers — encourages revision and resubmission."""
        subject = f"JAIGP Submission Not Accepted: {paper_title}"

        streak_note = ""
        if streak >= 2:
            streak_note = f"\n\nNote: This is your {streak}{'nd' if streak == 2 else 'rd'} consecutive borderline submission. A third will result in a temporary 48-hour submission pause."

        text_content = f"""Thank you for submitting to JAIGP.

After AI screening, your paper "{paper_title}" could not be accepted in its current form. The abstract did not provide sufficient evidence of academic substance for us to advance it through the pipeline.

We encourage you to revisit the submission and strengthen the abstract to more clearly articulate your research question, methodology, and findings before resubmitting.{streak_note}

We look forward to your revised submission.

Best regards,
JAIGP Team
https://jaigp.org"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Submission Not Accepted</h2>
            <p>Thank you for submitting to JAIGP.</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>After AI screening, your paper could not be accepted in its current form. The abstract did not provide sufficient evidence of academic substance for us to advance it through the pipeline.</p>
            <p>We encourage you to <strong>revisit your submission</strong> and strengthen the abstract to more clearly articulate your research question, methodology, and findings before resubmitting.</p>
            {"<p style='color:#b45309;'><strong>Note:</strong> This is your " + ("2nd" if streak == 2 else "3rd") + " consecutive borderline submission. A third will result in a temporary 48-hour submission pause.</p>" if streak >= 2 else ""}
            <p>We look forward to your revised submission.</p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_borderline_strike(self, to_email: str, paper_title: str, cooldown_until) -> bool:
        """Three consecutive borderlines — applies 48 h cooldown."""
        from datetime import timezone
        cooldown_str = cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if cooldown_until else "48 hours from now"
        subject = f"JAIGP Submission Paused: {paper_title}"

        text_content = f"""Thank you for submitting to JAIGP.

Your paper "{paper_title}" was not accepted after AI screening.

Because this is your third consecutive borderline submission, your account has been placed on a 48-hour submission pause (until {cooldown_str}).

We strongly encourage you to carefully review our submission guidelines and ensure your abstract clearly describes a real research contribution before submitting again.

Best regards,
JAIGP Team
https://jaigp.org"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Submission Paused</h2>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>Your paper was not accepted after AI screening.</p>
            <p style="color:#dc2626;"><strong>Because this is your third consecutive borderline submission, your account has been placed on a 48-hour submission pause until {cooldown_str}.</strong></p>
            <p>We strongly encourage you to review our submission guidelines and ensure your abstract clearly describes a real research contribution before submitting again.</p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_hard_rejection(self, to_email: str, paper_title: str, concern: str, cooldown_until) -> bool:
        """Hard rejection — paper deleted, 48 h cooldown applied."""
        cooldown_str = cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if cooldown_until else "48 hours from now"
        concern_text = concern or "The submission did not meet minimum academic content standards."
        subject = f"JAIGP Submission Rejected: {paper_title}"

        text_content = f"""Thank you for submitting to JAIGP.

We regret to inform you that your paper "{paper_title}" has been rejected by our AI screening system.

Reason: {concern_text}

Your account has been placed on a 48-hour submission pause (until {cooldown_str}). You may submit a new paper after this period.

If you believe this decision was made in error, please contact us at contact@jaigp.org.

Best regards,
JAIGP Team
https://jaigp.org"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Submission Rejected</h2>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p>We regret to inform you that your submission has been rejected by our AI screening system.</p>
            <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 15px;margin:20px 0;">
                <strong>Reason:</strong> {concern_text}
            </div>
            <p style="color:#dc2626;"><strong>Your account has been placed on a 48-hour submission pause until {cooldown_str}.</strong></p>
            <p>You may submit a new paper after this period. If you believe this decision was made in error, please <a href="mailto:contact@jaigp.org" style="color:#2563eb;">contact us</a>.</p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_stage_advance_notification(self, to_email: str, paper_title: str, new_stage_name: str, paper_url: str) -> bool:
        """Notify author that their paper advanced to a new stage."""
        subject = f"Paper Advanced to {new_stage_name}: {paper_title}"

        text_content = f"""Your paper "{paper_title}" has advanced to: {new_stage_name}.

View your paper: https://jaigp.org{paper_url}

Best regards,
JAIGP Team"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">Paper Advanced!</h2>
            <p>Your paper has advanced to a new stage:</p>
            <div class="highlight">
                <strong>Paper:</strong><br>{paper_title}
            </div>
            <p style="font-size: 18px; font-weight: bold; color: #10b981;">Now at: {new_stage_name}</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="https://jaigp.org{paper_url}" class="button-green">View Paper</a>
            </p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)

    def send_new_message_notification(self, to_email: str, sender_name: str, message_preview: str) -> bool:
        """Notify a user that they received a new direct message."""
        from html import escape
        subject = f"New message from {sender_name} on JAIGP"
        preview = message_preview[:200] if message_preview else ""

        text_content = f"""{sender_name} sent you a message on JAIGP:

"{preview}"

View and reply: https://jaigp.org/messages

Best regards,
JAIGP Team
https://jaigp.org"""

        html_body = f"""
            <h2 style="color: #1e293b; margin-top: 0;">New Message</h2>
            <p><strong>{escape(sender_name)}</strong> sent you a message:</p>
            <div class="highlight">
                {escape(preview)}{'...' if len(message_preview) > 200 else ''}
            </div>
            <p style="text-align: center; margin: 30px 0;">
                <a href="https://jaigp.org/messages" class="button">View Messages</a>
            </p>
            <p style="font-size:12px; color:#94a3b8;">You're receiving this because you have messaging enabled on your JAIGP profile. You can turn this off in your <a href="https://jaigp.org/auth/profile/edit" style="color:#2563eb;">profile settings</a>.</p>"""

        html_content = self._email_wrapper(html_body, text_content)
        return self._send_email(to_email, subject, text_content, html_content)


# Create singleton instance
email_service = EmailService()
