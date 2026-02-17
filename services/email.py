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


# Create singleton instance
email_service = EmailService()
