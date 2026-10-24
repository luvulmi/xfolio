"""가상 자료 아침 미리보기. 로그인·실제 승인·게시 기능은 별도 구현한다."""

import sqlite3

import streamlit as st

from xfolio.demo import demo_preview
from xfolio.storage import PreviewRepository, StorageError


def render_preview(store: PreviewRepository, *, storage_label: str) -> None:
    st.title("XFolio 아침 미리보기")
    st.caption(
        "지수와 뉴스는 모두 직접 작성한 가상 자료입니다. 실제 시세·뉴스 또는 AI 생성 결과가 아닙니다."
    )

    scenarios = {
        "뉴스 1건 · 글 2개": "news",
        "정상 수집 · 선정 뉴스 없음": "zero",
        "부분 수집 · 전체 보류": "partial",
    }
    scenario = st.selectbox("미리보기 상황", options=list(scenarios))
    preview = demo_preview(scenarios[scenario])

    left, right = st.columns([2, 1])
    with left:
        if preview.status == "held":
            st.warning("아침 전체 보류")
            for reason in preview.reasons:
                st.write(reason)
        else:
            st.success(f"검토용 가상 초안 · {len(preview.posts)}개 글")
        for position, post in enumerate(preview.posts, 1):
            with st.container(border=True):
                st.subheader(f"글 {position}")
                st.code(post.text, language=None, wrap_lines=True)
                st.caption(f"가중 길이 참고: {post.weighted_length_estimate}/280")
        st.caption(preview.length_notice)
        with st.expander("가상 원문 근거와 시각"):
            for evidence in preview.evidence:
                st.json(evidence)
            if not preview.evidence:
                st.write("연결된 선정 뉴스 근거가 없습니다.")

    with right:
        st.subheader("검토 상태")
        st.write("모드: dry_run")
        st.write("외부 게시: 없음")
        st.write("운영자 사실 검토: 미완료")
        st.caption("이 화면에는 실제 승인·X 전송 기능이 없습니다.")
        if st.button("가상 초안 저장"):
            try:
                saved = store.save(preview)
                st.success(
                    "저장했습니다." if saved else "같은 초안이 이미 저장돼 있습니다."
                )
            except (StorageError, sqlite3.Error, OSError, ValueError):
                st.error("DB 저장에 실패했습니다. 경로와 상태를 확인하세요.")
        st.caption(storage_label)

    st.subheader("저장한 가상 초안")
    try:
        stored = store.recent()
        if stored:
            st.dataframe(
                [
                    {
                        "버전": p.preview_id[:12],
                        "상태": p.status,
                        "글 수": len(p.posts),
                        "모드": p.mode,
                    }
                    for p in stored
                ],
                hide_index=True,
            )
        else:
            st.write("아직 저장한 초안이 없습니다.")
    except (StorageError, sqlite3.Error, OSError, ValueError):
        st.error("저장한 초안을 읽지 못했습니다.")
