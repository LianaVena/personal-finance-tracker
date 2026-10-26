"""Application theme declarations."""

from __future__ import annotations

from nicegui import ui


def apply_styles() -> None:
    """Apply the existing application theme."""
    ui.dark_mode().enable()
    ui.add_head_html("""
        <style>
            body, .q-page, .q-tab-panels, .q-tab-panel {
                background-color: #1b1b1b !important;
            }
            .q-card {
                background-color: #2b2b2b !important;
            }
            .q-table thead th {
                font-weight: 700 !important;
                text-align: center !important;
                color: #f8fafc !important;
                background-color: #3a3a3a !important;
                border-bottom: 2px solid #626262 !important;
            }
            .manage-table .q-table__middle {
                max-height: 18rem;
                overflow-y: auto;
            }
            .manage-table thead tr th {
                position: sticky;
                top: 0;
                z-index: 2;
            }
            .q-table tbody td {
                text-align: left !important;
            }
            .q-table tbody td.text-right {
                text-align: right !important;
            }
            .q-table th.q-table__col--selection,
            .q-table td.q-table__col--selection,
            .q-table .q-table__selection {
                display: none !important;
            }
            .manage-table .q-table tbody td {
                padding-top: 2px !important;
                padding-bottom: 2px !important;
            }
        </style>
    """)
