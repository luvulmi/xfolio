"""클라우드 진입점. 로그인·운영자 확인 전에는 저장소에 접근하지 않는다."""

import streamlit as st

from xfolio.cloud import operator_allowed
from xfolio.dashboard_ui import render_preview
from xfolio.storage import StorageError

st.set_page_config(page_title="XFolio", page_icon="📈")

try:
    allowed = st.secrets["XFOLIO_ADMIN_EMAILS"]
    url = st.secrets["XFOLIO_DATABASE_URL"]
    auth = st.secrets["auth"]
    configured = (
        isinstance(allowed, list)
        and bool(allowed)
        and all(isinstance(value, str) and value.strip() for value in allowed)
        and isinstance(url, str)
        and bool(url.strip())
        and all(
            auth.get(key) for key in ("client_id", "client_secret", "cookie_secret")
        )
        and auth.get("server_metadata_url")
        == "https://accounts.google.com/.well-known/openid-configuration"
    )
except (KeyError, FileNotFoundError):
    configured = False

if not configured:
    st.error("관리자 인증·저장소 설정이 준비되지 않았습니다.")
    st.stop()

if not st.user.is_logged_in:
    st.info("관리자 계정으로 로그인하세요.")
    if st.button("Google 로그인"):
        st.login()
    st.stop()

if not operator_allowed(dict(st.user), allowed):
    st.error("허용된 관리자 계정이 아니거나 로그인이 만료됐습니다.")
    if st.button("로그아웃"):
        st.logout()
    st.stop()

if st.sidebar.button("로그아웃"):
    st.logout()
    st.stop()

try:
    from xfolio.postgres import PostgresPreviewStore

    render_preview(
        PostgresPreviewStore(url), storage_label="가상 초안 저장소: PostgreSQL"
    )
except (StorageError, ValueError):
    st.error("저장소를 확인하지 못했습니다. 관리자 설정을 확인하세요.")
