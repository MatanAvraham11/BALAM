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
# Backend config – secrets are loaded from Streamlit Secrets (never hard-coded)
# ---------------------------------------------------------------------------

os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="בל\"מ → CSV",
    page_icon="📄",
    layout="centered",
)

st.markdown(
    "<style>body, .stApp {direction: rtl; text-align: right;}</style>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("כניסה למערכת")
    password = st.text_input("סיסמה", type="password")
    if st.button("כניסה", use_container_width=True):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("סיסמה שגויה, נסה שנית.")
    st.stop()

# ---------------------------------------------------------------------------
# Main area (only shown after successful login)
# ---------------------------------------------------------------------------

st.title('ממיר בל"מ ל-CSV')
st.markdown('העלה קובץ PDF של הזמנת רכש (בל"מ) וקבל קובץ CSV מפורסר.')

uploaded = st.file_uploader("בחר קובץ PDF", type=["pdf"])

if uploaded is not None:
    if st.button("המר ל-CSV", use_container_width=True):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = tmp.name

        try:
            with st.spinner("מחלץ טקסט מה-PDF..."):
                text = extract_text_from_pdf(tmp_path)

            with st.spinner("שולח ל-OpenAI לפרסור..."):
                order: PurchaseOrder = parse_with_openai(text)

            st.success(
                f'פורסר בהצלחה: בל"מ {order.balam_number}, '
                f"קניין: {order.buyer_name}, "
                f"{len(order.line_items)} שורות."
            )

            rows = [
                {
                    "Balam Number": order.balam_number,
                    "Buyer Name": order.buyer_name,
                    "Supplier SKU": item.supplier_sku,
                    "Required Quantity": item.required_quantity,
                    "Revision": item.revision,
                }
                for item in order.line_items
            ]
            df = pd.DataFrame(rows)

            st.subheader("תצוגה מקדימה")
            st.dataframe(df, use_container_width=True)

            buf = io.BytesIO()
            df.to_csv(buf, index=False, encoding="utf-8-sig")
            csv_bytes = buf.getvalue()

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
