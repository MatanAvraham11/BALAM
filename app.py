"""
Streamlit UI for the PDF-to-CSV purchasing-order parser.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import io
import os
import tempfile

import pandas as pd
import streamlit as st

from parse_balam import PurchaseOrder, extract_text_from_pdf, parse_with_openai

# ---------------------------------------------------------------------------
# Backend config
# ---------------------------------------------------------------------------

os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="נתיב | Nativ",
    page_icon="📋",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Minimal custom CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Hide Streamlit chrome */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* RTL */
    body, .stApp {
        direction: rtl;
        text-align: right;
    }

    /* Logo */
    .logo-wrap {
        text-align: center;
        padding: 2rem 0 0.8rem 0;
    }
    .logo-wrap h1 {
        font-size: 2.6rem;
        font-weight: 800;
        color: #2563eb;
        margin: 0;
        letter-spacing: -0.5px;
    }
    .logo-wrap p {
        font-size: 0.95rem;
        color: #64748b;
        margin: 0.3rem 0 0 0;
    }

    /* Divider */
    .sep {
        border: none;
        border-top: 1px solid #e2e8f0;
        margin: 1rem 0 1.5rem 0;
    }

    /* Info card */
    .info-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin: 1rem 0 1.5rem 0;
        display: flex;
        justify-content: center;
        gap: 3rem;
        flex-wrap: wrap;
    }
    .info-card .item .lbl {
        font-size: 0.78rem;
        color: #64748b;
        margin-bottom: 2px;
    }
    .info-card .item .val {
        font-size: 1.15rem;
        font-weight: 700;
        color: #1a1a2e;
    }

    /* Download button */
    .stDownloadButton > button {
        background-color: #2563eb !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
        padding: 0.65rem 1.5rem !important;
    }
    .stDownloadButton > button:hover {
        background-color: #1d4ed8 !important;
    }

    /* Convert button */
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
    }

    /* File uploader */
    [data-testid="stFileUploader"] {
        border: 2px dashed #cbd5e1;
        border-radius: 12px;
        padding: 0.8rem;
    }

    /* Section title */
    .sec-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1a1a2e;
        margin: 1.5rem 0 0.5rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="logo-wrap">'
    "<h1>נתיב | Nativ</h1>"
    '<p>מערכת לקליטת בל"מ</p>'
    "</div>",
    unsafe_allow_html=True,
)
st.markdown('<hr class="sep">', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

if not st.session_state.authenticated:
    password = st.text_input("סיסמה", type="password")
    if st.button("כניסה", use_container_width=True):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("סיסמה שגויה, נסה שנית.")
    st.stop()

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.markdown('העלה קובץ PDF של הזמנת רכש (בל"מ) וקבל קובץ CSV מפורסר.')

uploaded = st.file_uploader("בחר קובץ PDF", type=["pdf"])

if uploaded is not None:
    if st.button("המר ל-CSV", use_container_width=True, type="primary"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name

        try:
            with st.spinner("מחלץ טקסט מה-PDF..."):
                text = extract_text_from_pdf(tmp_path)

            with st.spinner("מעבד את ההזמנה..."):
                order: PurchaseOrder = parse_with_openai(text)

            st.success(f"עובד בהצלחה – {len(order.line_items)} שורות נמצאו")

            st.markdown(
                '<div class="info-card">'
                '<div class="item">'
                f'<div class="lbl">מספר בל"מ</div>'
                f'<div class="val">{order.balam_number}</div>'
                "</div>"
                '<div class="item">'
                f'<div class="lbl">קניין</div>'
                f'<div class="val">{order.buyer_name}</div>'
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )

            rows = [
                {
                    'מק"ט ספק': item.supplier_sku,
                    "כמות נדרשת": item.required_quantity,
                    "הוצאה": item.revision,
                }
                for item in order.line_items
            ]
            df = pd.DataFrame(rows)

            st.markdown(
                '<div class="sec-title">תצוגה מקדימה</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(df, use_container_width=True, hide_index=True)

            buf = io.StringIO()
            buf.write(f'מספר בל"מ: {order.balam_number}\n')
            buf.write(f"קניין: {order.buyer_name}\n")
            buf.write("\n")
            df.to_csv(buf, index=False)
            csv_bytes = buf.getvalue().encode("utf-8-sig")

            csv_filename = uploaded.name.rsplit(".", 1)[0] + ".csv"
            st.download_button(
                label="הורד CSV",
                data=csv_bytes,
                file_name=csv_filename,
                mime="text/csv",
                use_container_width=True,
            )

        except Exception as exc:
            st.error(f"שגיאה בעיבוד הקובץ: {exc}")

        finally:
            os.unlink(tmp_path)
