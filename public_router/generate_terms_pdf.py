from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import PageTemplate, Frame
from reportlab.lib import colors
import datetime

# ── Colour palette ────────────────────────────────────────────────────────────
BRAND_BLUE   = HexColor('#0c19dd')
DARK_BG      = HexColor('#0f0f1a')
HEADING_DARK = HexColor('#1a1a2e')
BODY_TEXT    = HexColor('#1a1a1a')
MUTED        = HexColor('#555555')
LIGHT_LINE   = HexColor('#dddddd')


def build_terms_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2.2*cm, rightMargin=2.2*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title="Primebooks Terms of Service",
        author="Prime Focus Uganda Limited",
        subject="Terms of Service — Primebooks SaaS Platform",
    )

    styles = getSampleStyleSheet()

    # ── Custom styles ─────────────────────────────────────────────────────────
    doc_title = ParagraphStyle(
        'DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=22,
        textColor=BRAND_BLUE, spaceAfter=6,
        alignment=TA_CENTER, leading=28,
    )
    doc_sub = ParagraphStyle(
        'DocSub', parent=styles['Normal'],
        fontName='Helvetica', fontSize=10,
        textColor=MUTED, spaceAfter=4,
        alignment=TA_CENTER,
    )
    h1 = ParagraphStyle(
        'H1', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=13,
        textColor=HEADING_DARK, spaceBefore=18, spaceAfter=6,
        leading=18, borderPad=4,
    )
    h2 = ParagraphStyle(
        'H2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=11,
        textColor=BODY_TEXT, spaceBefore=12, spaceAfter=4,
        leading=16,
    )
    body = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9.5,
        textColor=BODY_TEXT, spaceAfter=6,
        leading=15, alignment=TA_JUSTIFY,
    )
    bullet = ParagraphStyle(
        'Bullet', parent=body,
        leftIndent=18, bulletIndent=6, spaceAfter=4,
    )
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8,
        textColor=MUTED, alignment=TA_CENTER,
    )

    effective = datetime.date.today().strftime('%d %B %Y')
    story = []

    # ── Cover block ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("PRIMEBOOKS", doc_title))
    story.append(Paragraph("Terms of Service", ParagraphStyle(
        'DocTitle2', parent=doc_title, fontSize=17, textColor=BODY_TEXT,
    )))
    story.append(Paragraph(f"Effective Date: {effective}", doc_sub))
    story.append(Paragraph("Prime Focus Uganda Limited &nbsp;|&nbsp; primebooks.sale", doc_sub))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_BLUE, spaceAfter=16))

    # ── Introduction ──────────────────────────────────────────────────────────
    story.append(Paragraph("Introduction", h1))
    story.append(Paragraph(
        "These Terms of Service (\"Terms\") govern your access to and use of the Primebooks "
        "software-as-a-service platform (\"Platform\"), operated by <b>Prime Focus Uganda Limited</b> "
        "(BRN 80020003378756), Sentamu Kavule A, Nakawa, Kampala, Uganda (\"we\", \"us\", or \"Licensor\"). "
        "By creating an account, downloading the software, or otherwise using the Platform you agree to "
        "be bound by these Terms. If you do not agree, do not use the Platform.", body))

    # ── 1 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("1. Definitions", h1))
    defs = [
        ("<b>Platform</b>", "The Primebooks cloud-based business management application, including all modules, "
         "APIs, mobile and desktop clients, and related documentation."),
        ("<b>Account / Workspace</b>", "The dedicated tenant environment provisioned for your organisation "
         "upon successful signup."),
        ("<b>Authorised Users</b>", "Employees, contractors, or agents of your organisation who are "
         "granted access to the Platform under your subscription."),
        ("<b>Client Data</b>", "All data, records, and content you or your Authorised Users upload to or "
         "generate within the Platform."),
        ("<b>Subscription Plan</b>", "The Free, Basic, Pro, or Enterprise tier selected at signup or "
         "subsequently upgraded to."),
        ("<b>Support Period</b>", "The period during which we provide technical support and updates, "
         "as defined in your chosen plan."),
    ]
    for term, definition in defs:
        story.append(Paragraph(f"\u2022 {term}: {definition}", bullet))

    # ── 2 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("2. Account Registration", h1))
    story.append(Paragraph(
        "To use the Platform you must complete the signup form and provide accurate, current, and "
        "complete information. You are responsible for:", body))
    for item in [
        "Maintaining the confidentiality of your login credentials.",
        "All activity that occurs under your Account.",
        "Promptly notifying us of any unauthorised access at support@primefocus.ug.",
        "Ensuring all Authorised Users comply with these Terms.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))
    story.append(Paragraph(
        "We reserve the right to suspend or terminate accounts that provide false information "
        "or violate these Terms.", body))

    # ── 3 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("3. Licence Grant", h1))
    story.append(Paragraph(
        "Subject to your compliance with these Terms and timely payment of applicable fees, we grant you "
        "a <b>limited, non-exclusive, non-transferable, revocable</b> right to access and use the Platform "
        "solely for your internal business operations within Uganda (or as otherwise agreed in writing).", body))
    story.append(Paragraph("3.1 Free Trial", h2))
    story.append(Paragraph(
        "New accounts on the Free plan are provisioned as a free trial. Trial workspaces are subject to "
        "feature and storage limits set out on our pricing page. We may convert, suspend, or terminate "
        "a trial workspace at any time with reasonable notice.", body))

    # ── 4 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("4. Acceptable Use", h1))
    story.append(Paragraph("You agree <b>NOT</b> to:", body))
    for item in [
        "Reverse engineer, decompile, or attempt to derive the Platform's source code.",
        "Sublicense, resell, or provide Platform access to third parties without our written consent.",
        "Use the Platform to develop competing products or services.",
        "Share login credentials across the authorised-user limit.",
        "Upload content that is unlawful, harmful, or violates third-party rights.",
        "Circumvent security, licensing, or authentication mechanisms.",
        "Use the Platform for illegal purposes under Ugandan or applicable international law.",
        "Conduct denial-of-service attacks or introduce malicious code.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))
    story.append(Paragraph(
        "Violation of this section may result in immediate suspension or termination of your Account "
        "without refund.", body))

    # ── 5 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("5. Subscription Fees & Payment", h1))
    story.append(Paragraph(
        "Fees for paid plans are set out on our pricing page and may be updated with 30 days' notice.", body))
    for item in [
        "<b>Payment due:</b> Within 30 days of invoice unless otherwise specified.",
        "<b>Accepted methods:</b> Bank transfer, MTN/Airtel mobile money.",
        "<b>Late payment:</b> Licences may be suspended after a 15-day grace period; interest accrues at the maximum legal rate.",
        "<b>Taxes:</b> All fees are exclusive of VAT and applicable taxes, which are the Licensee's responsibility.",
        "<b>Refunds:</b> Fees are non-refundable except as required by applicable law or where we terminate without cause.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    # ── 6 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("6. Intellectual Property", h1))
    story.append(Paragraph(
        "Prime Focus Uganda Limited retains all right, title, and interest in the Platform, including "
        "all source code, algorithms, trademarks (\"PrimeBooks\", \"Prime Focus\"), and derivative works. "
        "These Terms do not transfer any ownership rights to you.", body))
    story.append(Paragraph(
        "<b>Client Data Ownership:</b> You retain ownership of all Client Data. We may access "
        "Client Data only to provide the service, for support purposes, or as required by law.", body))

    # ── 7 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("7. Data Security & Privacy", h1))
    story.append(Paragraph(
        "We implement industry-standard security measures including AES-256 encryption at rest, "
        "TLS 1.2+ in transit, regular security audits, and access controls. For full details see our "
        "Privacy Policy available at primebooks.sale/privacy-policy/.", body))
    for item in [
        "Cloud backups: automated with 30-day retention.",
        "Data location: Uganda; no transfer outside Uganda without your consent.",
        "Breach notification: within 72 hours of discovery.",
        "Compliance: Uganda Data Protection and Privacy Act, 2019.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    # ── 8 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("8. Support & Uptime", h1))
    story.append(Paragraph(
        "During the Support Period we provide email and phone support (5 AM – 12 PM EAT, "
        "Monday–Sunday, excluding public holidays). Cloud-hosted workspaces target 99.5% uptime "
        "during business hours. Response times:", body))
    rows = [
        ["Priority", "Target Response"],
        ["Critical (system down)", "4 business hours"],
        ["High (major feature broken)", "1 business day"],
        ["Medium (workaround available)", "3 business days"],
        ["Low (cosmetic)", "5 business days"],
    ]
    t = Table(rows, colWidths=[9*cm, 7*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BRAND_BLUE),
        ('TEXTCOLOR',  (0,0), (-1,0), white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [HexColor('#f9f9f9'), white]),
        ('GRID',       (0,0), (-1,-1), 0.5, LIGHT_LINE),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
    ]))
    story.append(Spacer(1, 0.2*cm))
    story.append(t)
    story.append(Spacer(1, 0.3*cm))

    # ── 9 ─────────────────────────────────────────────────────────────────────
    story.append(Paragraph("9. Warranties & Disclaimers", h1))
    story.append(Paragraph(
        "We warrant that the Platform will substantially conform to our published documentation "
        "for 90 days from delivery and that we have the right to licence the Platform as described. "
        "If it fails to conform, our sole obligation is to correct the non-conformity, provide a "
        "conforming replacement, or refund fees paid for the non-conforming period.", body))
    story.append(Paragraph(
        "<b>EXCEPT AS STATED ABOVE, THE PLATFORM IS PROVIDED \"AS IS\" WITHOUT WARRANTIES OF ANY KIND, "
        "INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR UNINTERRUPTED OPERATION. "
        "YOU ARE RESPONSIBLE FOR VALIDATING OUTPUTS AND MAINTAINING INDEPENDENT BACKUP SYSTEMS.</b>", body))

    # ── 10 ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("10. Limitation of Liability", h1))
    story.append(Paragraph(
        "TO THE MAXIMUM EXTENT PERMITTED BY LAW, OUR TOTAL LIABILITY SHALL NOT EXCEED THE TOTAL FEES "
        "PAID BY YOU IN THE 12 MONTHS PRECEDING THE CLAIM. IN NO EVENT SHALL WE BE LIABLE FOR INDIRECT, "
        "INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES, LOSS OF PROFITS, LOSS OF DATA, OR BUSINESS "
        "INTERRUPTION, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.", body))

    # ── 11 ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("11. Term & Termination", h1))
    for item in [
        "<b>Subscription licences</b> auto-renew unless cancelled 30 days before the renewal date.",
        "<b>Free plans</b> remain active until terminated by either party.",
        "<b>Termination for cause:</b> Either party may terminate on 30 days' written notice if the other materially breaches and fails to cure.",
        "<b>Immediate termination:</b> We may suspend or terminate without notice for violation of intellectual-property rights, reverse engineering, illegal use, or security risk to other tenants.",
        "<b>Effect:</b> All licences cease immediately. You may export Client Data within 30 days of termination of a cloud workspace.",
    ]:
        story.append(Paragraph(f"\u2022 {item}", bullet))

    # ── 12 ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("12. Confidentiality", h1))
    story.append(Paragraph(
        "Both parties agree to protect each other's Confidential Information with at least reasonable "
        "care, use it only for the purposes of this agreement, and not disclose it to third parties "
        "without prior written consent. Confidentiality obligations survive termination for 5 years.", body))

    # ── 13 ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("13. Modifications to These Terms", h1))
    story.append(Paragraph(
        "We may update these Terms with 30 days' notice. Continued use of the Platform after the "
        "effective date of changes constitutes acceptance. Material changes to perpetual licences "
        "require your explicit consent.", body))

    # ── 14 ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("14. Governing Law & Dispute Resolution", h1))
    story.append(Paragraph(
        "These Terms are governed by the <b>laws of the Republic of Uganda</b>. Disputes shall be "
        "resolved first by good-faith negotiation (30 days), then mediation before the Uganda "
        "Mediation Centre, then binding arbitration under the Arbitration and Conciliation Act "
        "(Uganda), with the seat in Kampala. Courts of Kampala have exclusive jurisdiction for "
        "matters not subject to arbitration.", body))

    # ── 15 ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("15. Contact Us", h1))
    story.append(Paragraph(
        "Questions about these Terms should be directed to:", body))
    story.append(Paragraph("\u2022 <b>Email:</b> primefocusug@gmail.com", bullet))
    story.append(Paragraph("\u2022 <b>Phone:</b> +256 785 230 670", bullet))
    story.append(Paragraph("\u2022 <b>WhatsApp:</b> wa.me/256785230670", bullet))
    story.append(Paragraph(
        "\u2022 <b>Address:</b> Prime Focus Uganda Limited, Sentamu Kavule A, Nakawa, Kampala, Uganda", bullet))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_LINE))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"© {datetime.date.today().year} Prime Focus Uganda Limited. All rights reserved. "
        f"Document generated {effective}.", footer_style))

    doc.build(story)
    print(f"Terms PDF saved to {output_path}")


if __name__ == '__main__':
    build_terms_pdf('/home/claude/terms_of_service.pdf')