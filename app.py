"""
Streamlit UI for Nativ — BLM parser & engineering drawing dimension extractor.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import io
import os
import tempfile

import pandas as pd
import streamlit as st

from parse_balam import PurchaseOrder, extract_text_from_pdf, parse_balam_text

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
        width: 100%;
    }
    [data-testid="stFileUploader"] section {
        border: 2px dashed #cbd5e1;
        border-radius: 12px;
        padding: 0;
        min-height: 168px;
    }
    [data-testid="stFileUploaderDropzone"] {
        min-height: 168px;
        padding: 1.25rem 1rem;
        width: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 0.45rem;
        align-items: center;
        justify-content: center;
        text-align: center;
    }
    [data-testid="stFileUploaderDropzone"] > div {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 0.35rem;
        width: 100%;
        text-align: center;
    }
    [data-testid="stFileUploaderDropzone"] button {
        display: block;
        margin: 0 auto;
    }
    [data-testid="stFileUploaderDropzone"] small {
        display: block;
        margin: 0 auto;
        text-align: center;
    }
    [data-testid="stFileUploader"]:first-of-type [data-testid="stFileUploaderDropzone"]::before {
        content: 'גרור לכאן קובץ בל"מ (PDF) או לחץ לבחירה';
        color: #1a1a2e;
        font-size: 1rem;
        font-weight: 500;
        line-height: 1.5;
        max-width: 90%;
        display: block;
        margin-bottom: 0.15rem;
    }
    [data-testid="stFileUploader"]:last-of-type [data-testid="stFileUploaderDropzone"]::before {
        content: 'גרור לכאן שרטוט הנדסי (PDF) או לחץ לבחירה';
        color: #1a1a2e;
        font-size: 1rem;
        font-weight: 500;
        line-height: 1.5;
        max-width: 90%;
        display: block;
        margin-bottom: 0.15rem;
    }

    /* Section title */
    .sec-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1a1a2e;
        margin: 1.5rem 0 0.5rem 0;
    }

    /* Tabs RTL fix */
    .stTabs [data-baseweb="tab-list"] {
        direction: rtl;
        gap: 8px;
        padding-bottom: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        font-weight: 600;
        padding: 8px 20px;
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
    "<p>חילוץ נתונים חכם ממסמכי רכש ושרטוטים הנדסיים</p>"
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
# Tabs
# ---------------------------------------------------------------------------

tab_balam, tab_drawing = st.tabs(['בל"מ', "שרטוט"])

# ========================== TAB 1: BLM ==========================

with tab_balam:
    st.markdown(
        'העלה קובץ PDF של בל"מ וקבל בשניות את כל הנתונים '
        "הרלוונטיים מוכנים לשימוש."
    )

    uploaded_balam = st.file_uploader(
        'גרור לכאן קובץ בל"מ (PDF) או לחץ לבחירה',
        type=["pdf"],
        key="balam_uploader",
        label_visibility="collapsed",
    )

    if uploaded_balam is not None:
        if st.button(
            "חלץ נתונים", use_container_width=True, type="primary", key="btn_balam"
        ):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uploaded_balam.getvalue())
                tmp_path = tmp.name

            try:
                with st.spinner('קורא את הבל"מ...'):
                    text = extract_text_from_pdf(tmp_path)

                with st.spinner("מחלץ נתונים..."):
                    order: PurchaseOrder = parse_balam_text(text)

                _raw_count = len(order.line_items)
                st.success(
                    f"הנתונים חולצו בהצלחה – נמצאו {_raw_count} פריטים"
                )

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

                # Aggregate rows with same SKU + revision, then add row numbers
                df = (
                    df.groupby(['מק"ט ספק', "הוצאה"], as_index=False, sort=False)
                    .agg({"כמות נדרשת": "sum"})
                )
                df.insert(0, "מספר", range(1, len(df) + 1))
                df = df[["מספר", 'מק"ט ספק', "כמות נדרשת", "הוצאה"]]

                st.markdown(
                    '<div class="sec-title">נתוני הפריטים</div>',
                    unsafe_allow_html=True,
                )
                st.dataframe(df, use_container_width=True, hide_index=True)

                buf = io.StringIO()
                buf.write(f'מספר בל"מ: {order.balam_number}\n')
                buf.write(f"קניין: {order.buyer_name}\n")
                buf.write("\n")
                df.to_csv(buf, index=False)
                csv_bytes = buf.getvalue().encode("utf-8-sig")

                csv_filename = uploaded_balam.name.rsplit(".", 1)[0] + ".csv"
                st.download_button(
                    label="הורד קובץ נתונים",
                    data=csv_bytes,
                    file_name=csv_filename,
                    mime="text/csv",
                    use_container_width=True,
                    key="dl_balam",
                )

            except Exception as exc:
                st.error(f"שגיאה בעיבוד הקובץ: {exc}")

            finally:
                os.unlink(tmp_path)

# ========================== TAB 2: DRAWING ==========================

with tab_drawing:
    from parse_drawing import (
        DrawingAnalysis,
        analyze_full_drawing,
        annotate_pdf,
        dimensions_to_csv_string,
        get_all_dimensions,
    )

    st.markdown(
        "העלה שרטוט הנדסי (PDF) — נחלץ את כל המידות, "
        "נמספר אותן ונחזיר CSV וגם שרטוט ממוספר."
    )

    uploaded_drawing = st.file_uploader(
        "גרור לכאן שרטוט הנדסי (PDF) או לחץ לבחירה",
        type=["pdf"],
        key="drawing_uploader",
        label_visibility="collapsed",
    )

    if uploaded_drawing is not None:
        if st.button(
            "חלץ מידות", use_container_width=True, type="primary", key="btn_drawing"
        ):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uploaded_drawing.getvalue())
                tmp_path = tmp.name

            try:
                with st.spinner("מנתח את השרטוט..."):
                    analysis: DrawingAnalysis = analyze_full_drawing(tmp_path)

                all_dims = get_all_dimensions(analysis)
                st.success(f"זוהו {len(all_dims)} מידות/הערות בשרטוט")

                st.markdown(
                    '<div class="info-card">'
                    '<div class="item">'
                    '<div class="lbl">שם החלק</div>'
                    f'<div class="val">{analysis.drawing_title}</div>'
                    "</div>"
                    '<div class="item">'
                    '<div class="lbl">מספר חלק</div>'
                    f'<div class="val">{analysis.part_number}</div>'
                    "</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

                # --- CSV preview ---
                st.markdown(
                    '<div class="sec-title">טבלת מידות</div>',
                    unsafe_allow_html=True,
                )
                dim_rows = [
                    {
                        "מספר": d.number,
                        "סוג מידה": d.dimension_type,
                        "ערך": d.value,
                    }
                    for d in all_dims
                ]
                df_dims = pd.DataFrame(dim_rows)
                st.dataframe(df_dims, use_container_width=True, hide_index=True)

                csv_str = dimensions_to_csv_string(analysis)
                csv_bytes = csv_str.encode("utf-8-sig")
                csv_name = uploaded_drawing.name.rsplit(".", 1)[0] + "_dimensions.csv"
                st.download_button(
                    label="הורד CSV מידות",
                    data=csv_bytes,
                    file_name=csv_name,
                    mime="text/csv",
                    use_container_width=True,
                    key="dl_drawing_csv",
                )

                # --- Annotated drawing ---
                st.markdown(
                    '<div class="sec-title">שרטוט ממוספר</div>',
                    unsafe_allow_html=True,
                )

                with st.spinner("ממספר את השרטוט..."):
                    annotated_pdf_bytes = annotate_pdf(tmp_path, analysis)

                import fitz as _fitz

                annotated_doc = _fitz.open(
                    stream=annotated_pdf_bytes, filetype="pdf"
                )
                for pg_idx in range(len(annotated_doc)):
                    pg = annotated_doc[pg_idx]
                    pix = pg.get_pixmap(matrix=_fitz.Matrix(2, 2), alpha=False)
                    st.image(
                        pix.tobytes("png"),
                        caption=f"עמוד {pg_idx + 1}",
                        use_container_width=True,
                    )
                annotated_doc.close()

                pdf_name = (
                    uploaded_drawing.name.rsplit(".", 1)[0] + "_annotated.pdf"
                )
                st.download_button(
                    label="הורד שרטוט ממוספר (PDF)",
                    data=annotated_pdf_bytes,
                    file_name=pdf_name,
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_drawing_pdf",
                )

            except Exception as exc:
                st.error(f"שגיאה בניתוח השרטוט: {exc}")

            finally:
                os.unlink(tmp_path)
