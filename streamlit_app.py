"""Streamlit Community Cloud entry point.

Community Cloud runs ``streamlit run streamlit_app.py`` from the repository
root. All UI, state, and configuration live in :mod:`lawsearch.app`.
"""

from lawsearch.app import main

main()
