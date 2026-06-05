"""Cognito Custom Message trigger — brand the codes Cognito emails users.

Cognito invokes this before sending a message (sign-up verification, resend,
email-attribute verification, sign-in OTP, password reset). We replace the plain
default text with a TimeBrew-branded HTML email. The literal code placeholder
(`event['request']['codeParameter']`, i.e. "{####}") MUST appear verbatim in the
emailMessage — Cognito substitutes the real code after this Lambda returns.

For any trigger source we don't explicitly style, we pass the event through
unchanged so Cognito uses its default (avoids breaking e.g. AdminCreateUser,
which needs a {username} placeholder we don't supply).
"""

# App theme (converted from the site's OKLCH green palette to email-safe hex).
PRIMARY = "#6DAE00"
ACCENT = "#8AC500"
DEEP = "#2F6F0F"
TINT_BG = "#E7F4D4"
BORDER = "#CEDFB4"
PAGE_BG = "#F4F7EE"
TEXT = "#1A1A1A"
BODY = "#4B5563"
MUTED = "#9CA3AF"

# triggerSource -> (subject, heading, intro builder)
STYLED_SOURCES = {
    "CustomMessage_SignUp": "verify",
    "CustomMessage_ResendCode": "verify",
    "CustomMessage_VerifyUserAttribute": "verify",
    "CustomMessage_Authentication": "signin",
    "CustomMessage_ForgotPassword": "reset",
}


def _copy(kind, name):
    hi = f"Hi {name}," if name else "Hi there,"
    if kind == "verify":
        return (
            "Verify your email",
            "Verify your email",
            f"{hi} welcome to TimeBrew! Enter the code below to verify your "
            "email and activate your account.",
        )
    if kind == "signin":
        return (
            "Your TimeBrew sign-in code",
            "Sign in to TimeBrew",
            f"{hi} use this one-time code to finish signing in.",
        )
    # reset
    return (
        "Your TimeBrew reset code",
        "Reset your access",
        f"{hi} use this one-time code to continue.",
    )


def _render(heading, intro, code_placeholder):
    return f"""\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:{PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE_BG}">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#FFFFFF;border:1px solid {BORDER};border-radius:16px;overflow:hidden;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
    <tr><td style="background:{DEEP};background:linear-gradient(135deg,{PRIMARY},{ACCENT});padding:22px 32px;">
      <span style="font-size:22px;font-weight:700;color:#FFFFFF;letter-spacing:-0.3px;">&#9749; TimeBrew</span>
    </td></tr>
    <tr><td style="padding:32px;">
      <h1 style="margin:0 0 12px;font-size:20px;font-weight:700;color:{TEXT};">{heading}</h1>
      <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:{BODY};">{intro}</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="background:{TINT_BG};border:1px solid {BORDER};border-radius:12px;padding:22px;">
          <div style="font-family:'Courier New',monospace;font-size:34px;font-weight:700;letter-spacing:8px;color:{DEEP};">{code_placeholder}</div>
        </td></tr>
      </table>
      <p style="margin:24px 0 0;font-size:13px;line-height:1.6;color:{MUTED};">This code expires shortly. If you didn&#39;t request it, you can safely ignore this email.</p>
    </td></tr>
    <tr><td style="padding:18px 32px;border-top:1px solid #EEF2E6;">
      <p style="margin:0;font-size:12px;color:{MUTED};">TimeBrew &middot; <a href="https://timebrew.news" style="color:{PRIMARY};text-decoration:none;">timebrew.news</a></p>
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def handler(event, context):
    trigger = event.get("triggerSource", "")
    print(f"[CUSTOM_MESSAGE] triggerSource={trigger}")

    kind = STYLED_SOURCES.get(trigger)
    if not kind:
        # Not a code email we style — let Cognito use its default message.
        return event

    request = event.get("request", {})
    code = request.get("codeParameter", "{####}")
    name = (request.get("userAttributes", {}) or {}).get("given_name", "").strip()

    subject, heading, intro = _copy(kind, name)
    event["response"]["emailSubject"] = subject
    event["response"]["emailMessage"] = _render(heading, intro, code)
    return event


# Keep a lambda_handler alias for consistency with the other functions.
lambda_handler = handler
