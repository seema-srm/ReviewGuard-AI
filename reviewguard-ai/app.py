"""Streamlit entry point for ReviewGuard AI Phase 1."""

import streamlit as st

from reviewguard.config import MAX_FILE_SIZE_BYTES, PHASE_2_MESSAGE
from reviewguard.file_utils import FileValidationError, validate_python_file


def main() -> None:
    st.set_page_config(page_title="ReviewGuard AI", page_icon="🛡️")
    st.title("ReviewGuard AI")
    st.write("Multi-Agent Code Review Platform")
    st.caption("Phase 1: upload and preview Python source. Maximum file size: 1 MB.")
    uploaded_file = st.file_uploader("Upload a Python file", type=["py"], max_upload_size=1)
    if uploaded_file is None:
        st.button("Review Code", disabled=True)
        return

    # Check size before reading; the shared validator also enforces the limit.
    if uploaded_file.size > MAX_FILE_SIZE_BYTES:
        st.error("File exceeds the 1 MB (1,048,576 bytes) limit.")
        return
    try:
        validated = validate_python_file(uploaded_file.name, uploaded_file.getvalue())
    except FileValidationError as exc:
        st.error(str(exc))
        return

    st.write(f"Filename: {validated.filename}")
    st.write(f"File size: {validated.size_bytes:,} bytes")
    st.write(f"Line count: {validated.line_count}")
    if not validated.source:
        st.info("This file is empty (0 lines).")
    st.code(validated.source, language="python")
    if st.button("Review Code"):
        st.info(PHASE_2_MESSAGE)


if __name__ == "__main__":
    main()
