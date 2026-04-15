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
# Session state defaults
# ---------------------------------------------------------------------------

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

# ---------------------------------------------------------------------------
# Theme CSS
# ---------------------------------------------------------------------------

LIGHT_THEME = """
:root {
    --bg: #f8f9fb;
    --card-bg: #ffffff;
    --text: #1a1a2e;
    --text-secondary: #555;
    --accent: #2563eb;
    --accent-hover: #1d4ed8;
    --border: #e2e8f0;
    --success-bg: #ecfdf5;
    --success-border: #6ee7b7;
}
"""

DARK_THEME = """
:root {
    --bg: #0f172a;
    --card-bg: #1e293b;
    --text: #e2e8f0;
    --text-secondary: #94a3b8;
    --accent: #3b82f6;
    --accent-hover: #60a5fa;
    --border: #334155;
    --success-bg: #064e3b;
    --success-border: #34d399;
}
"""

BASE_CSS = """
<style>
{theme}

#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}
header {{visibility: hidden;}}

body, .stApp {{
    direction: rtl;
    text-align: right;
}}

.stApp {{
    background-color: var(--bg);
}}

.logo-container {{
    text-align: center;
    padding: 1.5rem 0 0.5rem 0;
}}

.logo-title {{
    font-size: 2.4rem;
    font-weight: 800;
    color: var(--accent);
    letter-spacing: -0.5px;
    margin-bottom: 0;
    line-height: 1.2;
}}

.logo-subtitle {{
    font-size: 1rem;
    color: var(--text-secondary);
    margin-top: 0.2rem;
}}

.theme-toggle {{
    position: fixed;
    top: 14px;
    left: 14px;
    z-index: 9999;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 50%;
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}}

div[data-testid="stVerticalBlock"] > div {{
    color: var(--text);
}}

.info-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    margin: 1rem 0;
}}

.info-card .label {{
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-bottom: 0.15rem;
}}

.info-card .value {{
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text);
}}

.divider {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 1.2rem 0;
}}

.stButton > button {{
    border-radius: 10px;
    font-weight: 600;
    padding: 0.6rem 1.5rem;
    transition: all 0.2s;
}}

.stDownloadButton > button {{
    background-color: var(--accent) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
}}

.stDownloadButton > button:hover {{
    background-color: var(--accent-hover) !important;
}}

[data-testid="stFileUploader"] {{
    background: var(--card-bg);
    border: 2px dashed var(--border);
    border-radius: 12px;
    padding: 1rem;
}}

.section-header {{
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text);
    margin: 1.5rem 0 0.5rem 0;
}}
</style>
"""

theme_css = DARK_THEME if st.session_state.dark_mode else LIGHT_THEME
st.markdown(BASE_CSS.format(theme=theme_css), unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Dark mode toggle
# ---------------------------------------------------------------------------

col_spacer, col_toggle = st.columns([8, 1])
with col_toggle:
    icon = "☀️" if st.session_state.dark_mode else "🌙"
    if st.button(icon, key="theme_toggle", help="החלף מצב תצוגה"):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()

# ---------------------------------------------------------------------------
# Logo & Header
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="logo-container">'
    '<div class="logo-title">נתיב | Nativ</div>'
    '<div class="logo-subtitle">מערכת לקליטת בל"מ</div>'
    "</div>",
    unsafe_allow_html=True,
)

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

if not st.session_state.authenticated:
    st.markdown("")
    password = st.text_input("סיסמה", type="password", placeholder="הזן סיסמה...")
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

st.markdown(
    'העלה קובץ PDF של הזמנת רכש (בל"מ) וקבל קובץ CSV מפורסר.',
)

st.markdown("")

uploaded = st.file_uploader("בחר קובץ PDF", type=["pdf"], label_visibility="collapsed")

if uploaded is not None:
    st.markdown("")
    if st.button("⚡ המר ל-CSV", use_container_width=True):
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
                f'<div style="display:flex; gap:3rem; justify-content:center; flex-wrap:wrap;">'
                f'<div><div class="label">מספר בל"מ</div><div class="value">{order.balam_number}</div></div>'
                f'<div><div class="label">קניין</div><div class="value">{order.buyer_name}</div></div>'
                f"</div></div>",
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

            st.markdown('<div class="section-header">תצוגה מקדימה</div>', unsafe_allow_html=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

            buf = io.StringIO()
            buf.write(f'מספר בל"מ: {order.balam_number}\n')
            buf.write(f"קניין: {order.buyer_name}\n")
            buf.write("\n")
            df.to_csv(buf, index=False)
            csv_bytes = buf.getvalue().encode("utf-8-sig")

            csv_filename = uploaded.name.rsplit(".", 1)[0] + ".csv"

            st.markdown("")
            st.download_button(
                label="📥 הורד CSV",
                data=csv_bytes,
                file_name=csv_filename,
                mime="text/csv",
                use_container_width=True,
            )

        except Exception as exc:
            st.error(f"שגיאה בעיבוד הקובץ: {exc}")

        finally:
            os.unlink(tmp_path)
