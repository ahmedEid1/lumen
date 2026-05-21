"""Lightweight branded HTML wrapper for transactional emails.

Every transactional email Lumen sends (password reset, email verify,
email change confirm) now goes out as multipart with both plain
text *and* a styled HTML alternative. The HTML is a single inlined-
CSS layout so it renders consistently across Gmail / Outlook /
Apple Mail without external stylesheets (which most clients strip).

No template engine — Python f-strings against a tiny shape. Pulling
in Jinja2 just for transactional emails would add a dependency and
a templates directory for what's currently three messages with the
same structure: heading, body paragraph, optional CTA button,
footer.
"""

from __future__ import annotations

from html import escape


def render_branded_html(
    *,
    heading: str,
    body_paragraphs: list[str],
    cta_url: str | None = None,
    cta_label: str | None = None,
    footer: str = (
        "If you didn't expect this email, you can safely ignore it — nothing changes "
        "until you click the link."
    ),
) -> str:
    """Build a self-contained HTML body for a transactional email."""
    paragraphs_html = "\n".join(
        f'<p style="margin:0 0 16px 0;color:#111;font-size:15px;line-height:1.55;">{escape(p)}</p>'
        for p in body_paragraphs
    )
    cta_html = ""
    if cta_url and cta_label:
        # Use a table-based button — every email client respects it,
        # unlike pure CSS buttons which render as plain text on Outlook.
        cta_html = f"""
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;">
          <tr>
            <td style="background:#0f172a;border-radius:6px;">
              <a href="{escape(cta_url)}" style="display:inline-block;padding:12px 24px;color:#fff;text-decoration:none;font-weight:600;font-size:14px;">
                {escape(cta_label)}
              </a>
            </td>
          </tr>
        </table>
        <p style="margin:0 0 16px 0;color:#475569;font-size:13px;word-break:break-all;">
          Or paste this link into your browser: <a href="{escape(cta_url)}" style="color:#0f172a;">{escape(cta_url)}</a>
        </p>
        """
    return f"""\
<!doctype html>
<html>
<head><meta charset="utf-8"><title>{escape(heading)}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f1f5f9;padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560" style="max-width:560px;background:#fff;border-radius:8px;overflow:hidden;">
          <tr>
            <td style="padding:32px 32px 0 32px;">
              <h1 style="margin:0 0 8px 0;color:#0f172a;font-size:20px;font-weight:600;">Lumen</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 32px 32px;">
              <h2 style="margin:0 0 16px 0;color:#0f172a;font-size:18px;font-weight:600;">{escape(heading)}</h2>
              {paragraphs_html}
              {cta_html}
              <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
              <p style="margin:0;color:#64748b;font-size:12px;line-height:1.5;">{escape(footer)}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
