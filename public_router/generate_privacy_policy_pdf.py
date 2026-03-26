from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
import datetime

BRAND_BLUE   = HexColor('#0c19dd')
HEADING_DARK = HexColor('#1a1a2e')
BODY_TEXT    = HexColor('#1a1a1a')
MUTED        = HexColor('#555555')
LIGHT_LINE   = HexColor('#dddddd')


def build_privacy_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2.2*cm, rightMargin=2.2*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title="Primebooks Privacy Policy",
        author="Prime Focus Uganda Limited",
        subject="Privacy Policy — Primebooks Platform",
    )

    styles = getSampleStyleSheet()

    doc_title = ParagraphStyle('DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=22, textColor=BRAND_BLUE,
        spaceAfter=6, alignment=TA_CENTER, leading=28)
    doc_sub = ParagraphStyle('DocSub', parent=styles['Normal'],
        fontName='Helvetica', fontSize=10, textColor=MUTED,
        spaceAfter=4, alignment=TA_CENTER)
    h1 = ParagraphStyle('H1', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=13, textColor=HEADING_DARK,
        spaceBefore=18, spaceAfter=6, leading=18)
    h2 = ParagraphStyle('H2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=11, textColor=BODY_TEXT,
        spaceBefore=12, spaceAfter=4, leading=16)
    body = ParagraphStyle('Body', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9.5, textColor=BODY_TEXT,
        spaceAfter=6, leading=15, alignment=TA_JUSTIFY)
    bullet = ParagraphStyle('Bullet', parent=body,
        leftIndent=18, bulletIndent=6, spaceAfter=4)
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, textColor=MUTED, alignment=TA_CENTER)

    effective = datetime.date.today().strftime('%d %B %Y')
    story = []

    # Cover
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("PRIMEBOOKS", doc_title))
    story.append(Paragraph("Privacy Policy", ParagraphStyle(
        'DocTitle2', parent=doc_title, fontSize=17, textColor=BODY_TEXT)))
    story.append(Paragraph(f"Effective Date: {effective}", doc_sub))
    story.append(Paragraph("Prime Focus Uganda Limited &nbsp;|&nbsp; primebooks.sale", doc_sub))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_BLUE, spaceAfter=16))

    story.append(Paragraph("Our Commitment to Your Privacy", h1))
    story.append(Paragraph(
        "Prime Focus Uganda Limited (\"we\", \"us\", or \"our\") operates the Primebooks platform. "
        "We are committed to protecting your personal data in accordance with the "
        "<b>Uganda Data Protection and Privacy Act, 2019</b> and other applicable laws. "
        "This Privacy Policy explains what data we collect, how we use it, and your rights.", body))

    story.append(Paragraph("1. Who This Policy Applies To", h1))
    story.append(Paragraph(
        "This policy applies to all visitors to primebooks.sale, registered account holders, "
        "Authorised Users of a Primebooks workspace, and anyone who contacts us for support. "
        "\"You\" refers to any of the above.", body))

    story.append(Paragraph("2. Data We Collect", h1))
    story.append(Paragraph("2.1 Information You Provide Directly", h2))
    for item in [
        "<b>Account registration:</b> company name, subdomain, email address, phone number, country, first/last name, password (hashed — never stored in plain text).",
        "<b>Business details:</b> industry, business type, estimated number of users.",
        "<b>Client Data:</b> invoices, inventory records, customer records, financial transactions, and all other data you enter into the Platform.",
        "<b>Support communications:</b> tickets, chat messages, emails.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    story.append(Paragraph("2.2 Data Collected Automatically", h2))
    for item in [
        "<b>Log data:</b> IP address, browser type and version, pages visited, timestamps, referring URL.",
        "<b>Device data:</b> operating system, screen resolution, device type.",
        "<b>Usage data:</b> features used, module interactions, session duration — used only for product improvement.",
        "<b>Cookies:</b> session cookies (required for login), preference cookies (theme, language). See Section 8.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    story.append(Paragraph("2.3 Data from Third Parties", h2))
    story.append(Paragraph(
        "If you sign up via a referral partner, we receive your company name and email from that "
        "partner solely to attribute the referral. We do not purchase marketing lists or "
        "receive data from data brokers.", body))

    story.append(Paragraph("3. How We Use Your Data", h1))
    purposes = [
        ("Provide the Platform", "Provision your workspace, authenticate users, process transactions."),
        ("Billing & payments", "Generate invoices, process payments, handle subscription management."),
        ("Support", "Respond to tickets, diagnose technical issues, provide onboarding assistance."),
        ("Security", "Detect fraud, prevent abuse, monitor for unauthorised access."),
        ("Product improvement", "Aggregate usage analytics to guide feature development (never individual profiling for advertising)."),
        ("Legal compliance", "Meet obligations under Ugandan law, respond to lawful requests from authorities."),
        ("Communications", "Send transactional emails (account creation, password reset, invoices). We do not send marketing emails without your consent."),
    ]
    for purpose, detail in purposes:
        story.append(Paragraph(f"\u2022 <b>{purpose}:</b> {detail}", bullet))

    story.append(Paragraph("4. Legal Basis for Processing", h1))
    story.append(Paragraph(
        "Under the Uganda Data Protection and Privacy Act, 2019, we process your personal data on the following bases:", body))
    for item in [
        "<b>Contract performance:</b> processing necessary to provide the Platform under our Terms of Service.",
        "<b>Legitimate interests:</b> fraud prevention, security monitoring, product analytics.",
        "<b>Legal obligation:</b> tax records, regulatory reporting.",
        "<b>Consent:</b> marketing communications (where applicable — you may withdraw consent at any time).",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    story.append(Paragraph("5. Data Sharing & Disclosure", h1))
    story.append(Paragraph(
        "We do <b>not</b> sell, rent, or trade your personal data. We may share data only as follows:", body))
    for item in [
        "<b>Service providers:</b> hosting infrastructure, email delivery, payment processing — bound by data-processing agreements and confidentiality obligations.",
        "<b>Legal requirements:</b> when required by Ugandan law, court order, or regulatory authority — we will notify you where legally permitted.",
        "<b>Business transfers:</b> in the event of a merger or acquisition, data may transfer to the successor entity under equivalent protections.",
        "<b>Your consent:</b> any other sharing only with your explicit prior consent.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    story.append(Paragraph("6. Data Location & International Transfers", h1))
    story.append(Paragraph(
        "Your Client Data is stored on servers located in <b>Uganda</b>. We do not transfer personal "
        "data outside Uganda without your explicit consent and appropriate safeguards as required by the "
        "Uganda Data Protection and Privacy Act, 2019.", body))

    story.append(Paragraph("7. Data Retention", h1))
    for item in [
        "<b>Active accounts:</b> retained for the duration of your subscription.",
        "<b>After termination:</b> Client Data is available for export for 30 days, then securely deleted within 90 days.",
        "<b>Backups:</b> automated backups retained for 30 days.",
        "<b>Log data:</b> retained for up to 12 months for security and debugging purposes.",
        "<b>Legal obligations:</b> financial records retained for 7 years as required by Ugandan tax law.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    story.append(Paragraph("8. Cookies", h1))
    story.append(Paragraph(
        "We use only essential cookies required for the Platform to function:", body))
    for item in [
        "<b>Session cookie (sessionid):</b> keeps you logged in during a browser session.",
        "<b>CSRF token (csrftoken):</b> protects against cross-site request forgery.",
        "<b>Theme preference:</b> remembers your light/dark mode choice.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))
    story.append(Paragraph(
        "We do not use advertising, tracking, or analytics cookies from third parties. "
        "You can disable cookies in your browser but some Platform features will not function correctly.", body))

    story.append(Paragraph("9. Security", h1))
    story.append(Paragraph(
        "We implement the following technical and organisational measures to protect your data:", body))
    for item in [
        "AES-256 encryption for data at rest.",
        "TLS 1.2+ encryption for all data in transit.",
        "Regular third-party security audits and vulnerability assessments.",
        "Role-based access controls; staff access to Client Data is limited and logged.",
        "Multi-tenant data isolation: your workspace data is logically separated from all other tenants.",
        "Breach notification: we will notify you within 72 hours of discovering a breach affecting your data.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    story.append(Paragraph("10. Your Rights", h1))
    story.append(Paragraph(
        "Under the Uganda Data Protection and Privacy Act, 2019, you have the right to:", body))
    for item in [
        "<b>Access:</b> request a copy of the personal data we hold about you.",
        "<b>Correction:</b> request correction of inaccurate or incomplete data.",
        "<b>Deletion:</b> request deletion of your personal data (subject to legal retention obligations).",
        "<b>Portability:</b> export your Client Data in a machine-readable format at any time from your workspace settings.",
        "<b>Restriction:</b> request that we restrict processing in certain circumstances.",
        "<b>Object:</b> object to processing based on legitimate interests.",
        "<b>Withdraw consent:</b> where processing is based on consent, withdraw it at any time without affecting prior processing.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))
    story.append(Paragraph(
        "To exercise any of these rights, contact us at <b>primefocusug@gmail.com</b>. "
        "We will respond within 30 days.", body))

    story.append(Paragraph("11. Children's Privacy", h1))
    story.append(Paragraph(
        "The Platform is intended for business use and is not directed at individuals under 18 years "
        "of age. We do not knowingly collect personal data from minors. If you believe we have "
        "inadvertently collected such data, please contact us immediately.", body))

    story.append(Paragraph("12. Changes to This Policy", h1))
    story.append(Paragraph(
        "We may update this Privacy Policy from time to time. We will notify you of material changes "
        "by email or by a prominent notice on the Platform at least 30 days before the change takes "
        "effect. Continued use of the Platform after the effective date constitutes acceptance.", body))

    story.append(Paragraph("13. Contact & Complaints", h1))
    story.append(Paragraph(
        "For privacy questions, data requests, or complaints:", body))
    story.append(Paragraph("\u2022 <b>Data Controller:</b> Prime Focus Uganda Limited", bullet))
    story.append(Paragraph("\u2022 <b>Email:</b> primefocusug@gmail.com", bullet))
    story.append(Paragraph("\u2022 <b>Phone:</b> +256 785 230 670", bullet))
    story.append(Paragraph(
        "\u2022 <b>Address:</b> Sentamu Kavule A, Nakawa, Kampala, Uganda", bullet))
    story.append(Paragraph(
        "You also have the right to lodge a complaint with the <b>National Information Technology "
        "Authority (NITA-U)</b>, which supervises data protection in Uganda.", body))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_LINE))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"© {datetime.date.today().year} Prime Focus Uganda Limited. All rights reserved. "
        f"Document generated {effective}.", footer_style))

    doc.build(story)
    print(f"Privacy PDF saved to {output_path}")


if __name__ == '__main__':
    build_privacy_pdf('/home/claude/privacy_policy.pdf')