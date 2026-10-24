"""로컬 가상 미리보기 진입점."""

import os

import streamlit as st

from xfolio.dashboard_ui import render_preview
from xfolio.storage import DEFAULT_DB, StorageError, configured_store

st.set_page_config(page_title="XFolio", page_icon="\U0001f4c8")
try:
    label = (
        "PostgreSQL"
        if os.environ.get("XFOLIO_DATABASE_URL", "").strip()
        else DEFAULT_DB.name
    )
    render_preview(configured_store(), storage_label=f"가상 초안 저장소: {label}")
except (StorageError, ValueError):
    st.error("설정된 가상 초안 저장소를 열지 못했습니다.")
