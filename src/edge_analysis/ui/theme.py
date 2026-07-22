from __future__ import annotations 
from pathlib import Path
import base64
import streamlit as st
import altair as alt
import streamlit.components.v1 as components
from PIL import Image

# ───────────────────────── Brand / assets ─────────────────────────
PURPLE_HEX = "#4800ff"
ASSETS_DIR = Path("assets")
RAW_ICON   = ASSETS_DIR / "edge_favicon_mark.png"
FAVI_PNG   = ASSETS_DIR / "edge_favicon_transparent.png"
HEADER_LOGO_LIGHT = ASSETS_DIR / "edge_logo.png"
HEADER_LOGO_DARK  = ASSETS_DIR / "edge_logo_dark.png"  # kept for compatibility


# ───────────────────────── Light-only palette ─────────────────────
LIGHT = dict(
    bg="#f6f7fb", card="#ffffff", ink="#0f172a",
    muted="#64748b", grid="#e5e7eb", hover="#f3f4f6",
    chart_bg="#ffffff", accent=PURPLE_HEX, toggle="#000000", border="#d1d5db"
)


# ─────────────────────── CONSOLIDATED THEME INJECTION ──────────────
def inject_theme():
    """
    SINGLE injection point for ALL Edge Analysis CSS.
    Called once in app.py after st.set_page_config().
    
    This consolidates:
    - app.py _inject_all_styles()
    - app.py _inject_dropdown_css()
    - app.py inject_soft_bg()
    - app.py inject_label_fix()
    - tabs.py CSS patches (lines 26-76)
    - theme.py apply_theme() & inject_global_css()
    """
    c = LIGHT
    st.session_state["ui_theme"] = "light"
    
    # Configure Altair charts (light theme)
    def _alt():
        return {"config":{
            "background": c["chart_bg"],
            "view": {"stroke": "transparent", "fill": c["chart_bg"]},
            "axis": {"labelColor": c["ink"], "titleColor": c["ink"],
                     "gridColor": c["grid"], "tickColor": c["grid"], "grid": True},
            "legend": {"labelColor": c["ink"], "titleColor": c["ink"]},
        }}
    alt.themes.register("edge_light", _alt)
    alt.themes.enable("edge_light")
    
    # Chevron SVG for dropdowns
    chevron_svg = (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
        "<path d='M6 9l6 6 6-6' fill='none' stroke='%230f172a' stroke-width='2' "
        "stroke-linecap='round' stroke-linejoin='round'/>"
        "</svg>"
    )
    
    # ALL CSS IN ONE PLACE
    st.markdown(f"""
    <style>
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* CSS VARIABLES                                                            */
    /* ═══════════════════════════════════════════════════════════════════════ */
    :root {{
      --accent: {c['accent']};
      --ink: {c['ink']};
      --muted: {c['muted']};
      --bg: {c['bg']};
      --card: {c['card']};
      --grid: {c['grid']};
      --hover: {c['hover']};
      --toggle: {c['toggle']};
      --border: {c['border']};
      --brand: {PURPLE_HEX};
      --ea-bg-soft: #f5f6fb;
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* MOBILE TYPOGRAPHY & SPACING                                              */
    /* ═══════════════════════════════════════════════════════════════════════ */
    @media (max-width: 480px) {{
      .block-container {{
        padding-left: .6rem !important;
        padding-right: .6rem !important;
        padding-top: .5rem !important;
      }}
      html {{ font-size: 14px; }}
      body, p, span, div {{ line-height: 1.15; }}
      
      .entry-card {{
        padding: 14px 14px;
        border-radius: 12px;
      }}
      .entry-card h2 {{
        font-size: 20px;
        margin: 0 0 6px 0;
      }}
      
      table.entry-model-table, table.session-perf-table, table.day-perf-table {{
        font-size: 12px;
        table-layout: fixed;
        width: 100%;
      }}
      .entry-model-table thead th,
      .entry-model-table tbody td,
      .session-perf-table thead th,
      .session-perf-table tbody td,
      .day-perf-table thead th,
      .day-perf-table tbody td {{
        padding: 8px 6px;
        line-height: 1.15;
        word-break: break-word;
        hyphens: auto;
      }}
      .entry-model-table td:nth-child(2),
      .session-perf-table td:nth-child(2),
      .day-perf-table td:nth-child(2) {{ width: 64px; }}
      .entry-model-table td:nth-child(3),
      .session-perf-table td:nth-child(3),
      .day-perf-table td:nth-child(3) {{ width: 72px; }}
      
      .stTabs [data-baseweb="tab"] {{ padding: 6px 10px; }}
      .stTabs [data-baseweb="tab"] p {{
        font-size: 14px;
        margin: 0;
      }}
      
      div[data-testid="stMetricValue"] {{ font-size: 24px; }}
      div[data-testid="stMetricDelta"] {{ font-size: 12px; }}
      .stMetric {{ padding: 6px 8px; }}
      
      .stAltairChart, .stPlotlyChart, .stVegaLiteChart {{
        margin-top: 4px;
        margin-bottom: 8px;
      }}
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* ZERO-SCROLL MOBILE OPTIMIZATION (≤480px)                                 */
    /* ═══════════════════════════════════════════════════════════════════════ */
    @media (max-width: 480px) {{
      html {{ font-size: 12.5px; }}
      .block-container {{
        padding-left: .45rem !important;
        padding-right: .45rem !important;
        padding-top: .4rem !important;
      }}
      
      .stMetric {{ padding: 4px 6px !important; }}
      div[data-testid="stMetricValue"] {{ font-size: 20px !important; }}
      div[data-testid="stMetricDelta"] {{ font-size: 11px !important; }}
      
      .entry-card h2 {{
        font-size: 17px !important;
        margin: 0 0 4px 0 !important;
      }}
      h2, h3 {{
        font-size: 19px !important;
        margin: 8px 0 6px 0 !important;
      }}
      
      table.entry-model-table,
      table.session-perf-table,
      table.day-perf-table {{
        width: 100% !important;
        table-layout: fixed !important;
        font-size: 10.5px !important;
        border-spacing: 0 !important;
        min-width: 0 !important;
      }}
      .entry-model-table thead th,
      .entry-model-table tbody td,
      .session-perf-table thead th,
      .session-perf-table tbody td,
      .day-perf-table thead th,
      .day-perf-table tbody td {{
        padding: 4px 4px !important;
        line-height: 1.05 !important;
        word-break: break-word !important;
        overflow-wrap: anywhere !important;
        white-space: normal !important;
        hyphens: auto !important;
      }}
      .entry-model-table th:nth-child(1),
      .entry-model-table td:nth-child(1),
      .session-perf-table th:nth-child(1),
      .session-perf-table td:nth-child(1),
      .day-perf-table th:nth-child(1),
      .day-perf-table td:nth-child(1) {{
        width: 42% !important;
      }}
      
      .stTabs [data-baseweb="tab"] {{ padding: 5px 8px !important; }}
      .stTabs [data-baseweb="tab"] p {{
        font-size: 13px !important;
        margin: 0 !important;
      }}
      .spacer-12 {{ height: 6px !important; }}
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* CARD & TABLE STYLING                                                     */
    /* ═══════════════════════════════════════════════════════════════════════ */
    .entry-card {{
      background: #fff;
      border-radius: 16px;
      padding: 20px 24px;
      box-shadow: 0 6px 22px rgba(0,0,0,.06);
    }}
    .entry-card h2 {{
      margin: 0 0 10px 0;
      font-size: 28px;
      line-height: 1.2;
      font-weight: 800;
    }}
    
    .entry-model-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 16px;
      table-layout: fixed;
      min-width: 520px;
    }}
    .entry-model-table thead th {{
      text-align: left;
      font-weight: 700;
      background: #f6f7fb;
      padding: 12px 10px;
      border-bottom: 2px solid {PURPLE_HEX};
    }}
    .entry-model-table tbody td {{
      padding: 12px 10px;
      border-bottom: 1px solid #eef0f5;
    }}
    .entry-model-table tbody tr:nth-child(even) td {{
      background: #fafbff;
    }}
    .entry-model-table td.num,
    .entry-model-table th.num {{
      text-align: right;
    }}
    .entry-model-table td.text,
    .entry-model-table th.text {{
      text-align: left;
    }}
    .entry-card .table-wrap {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    .entry-model-table th,
    .entry-model-table td {{
      word-wrap: break-word;
      overflow-wrap: anywhere;
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* MOBILE TAB WRAPPING (≤768px)                                             */
    /* ═══════════════════════════════════════════════════════════════════════ */
    @media (max-width: 768px) {{
      div[data-baseweb="tab-list"] {{
        flex-wrap: wrap !important;
        overflow: visible !important;
        gap: 8px 12px !important;
      }}
      div[data-baseweb="tab"] {{
        flex: 0 1 auto !important;
        margin: 0 !important;
      }}
      div[data-baseweb="tab-list"]::before,
      div[data-baseweb="tab-list"]::after {{
        content: none !important;
        display: none !important;
      }}
      .stTabs [data-baseweb="tab-highlight"] {{
        display: none !important;
      }}
      .stTabs [role="tab"][aria-selected="true"] {{
        border-bottom: none !important;
        box-shadow: none !important;
      }}
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* DATE PICKER STYLING                                                      */
    /* ═══════════════════════════════════════════════════════════════════════ */
    
    /* Input container */
    [data-testid="stDateInput"] > div > div {{
      border-radius: 12px !important;
      border: 1px solid #e5e7eb !important;
      background-color: #ffffff !important;
      overflow: hidden !important;
    }}
    [data-testid="stDateInput"] input {{
      background-color: #ffffff !important;
      color: #0f172a !important;
      border: none !important;
      box-shadow: none !important;
    }}
    [data-testid="stDateInput"] input:focus {{
      outline: 2px solid {PURPLE_HEX} !important;
      box-shadow: 0 0 0 1px rgba(72,0,255,0.5) !important;
    }}
    [data-testid="stDateInput"] div:focus {{
      outline: none !important;
    }}
    
    /* Calendar popup - FORCE LIGHT THEME */
    .stDateInput [role="dialog"],
    .stDateInput [data-baseweb="popover"],
    .stDateInput [data-baseweb="popover"] > div {{
      background-color: #ffffff !important;
      color: #0f172a !important;
      border: 1px solid #d1d5db !important;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15) !important;
    }}
    
    .stDateInput [role="dialog"] [data-baseweb="datepicker"],
    .stDateInput [data-baseweb="popover"] [data-baseweb="datepicker"],
    .stDateInput [role="dialog"] [data-baseweb="datepicker"] > div,
    .stDateInput [data-baseweb="popover"] [data-baseweb="datepicker"] > div {{
      background-color: #ffffff !important;
      color: #0f172a !important;
    }}
    
    /* Calendar header and body */
    .stDateInput [data-baseweb="calendar"],
    .stDateInput [data-baseweb="datepicker"],
    .stDateInput [data-baseweb="calendar"] > div,
    .stDateInput [data-baseweb="datepicker"] > div {{
      background-color: #ffffff !important;
      color: #0f172a !important;
    }}
    
    /* Month/Year dropdowns - FORCE DARK TEXT */
    .stDateInput [data-baseweb="select"],
    .stDateInput [data-baseweb="select"] div,
    .stDateInput [data-baseweb="select"] span,
    .stDateInput [data-baseweb="select"] button {{
      background-color: #ffffff !important;
      color: #0f172a !important;
    }}
    
    /* Dropdown menu items */
    .stDateInput [data-baseweb="menu"] [data-baseweb="menu-item"] {{
      background-color: #ffffff !important;
      color: #0f172a !important;
    }}
    .stDateInput [data-baseweb="menu"] [data-baseweb="menu-item"]:hover,
    .stDateInput [data-baseweb="menu"] [data-baseweb="menu-item"][aria-selected="true"] {{
      background-color: rgba(148,163,184,0.18) !important;
      color: #0f172a !important;
    }}
    
    /* Day buttons */
    .stDateInput [data-baseweb="calendar"] button {{
      background: transparent !important;
      color: #0f172a !important;
    }}
    .stDateInput [data-baseweb="calendar"] button:hover {{
      background-color: rgba(148,163,184,0.18) !important;
    }}
    
    /* Selected day - Edge purple (PATCH 3 from tabs.py) */
    .stDateInput .react-datepicker__day--selected,
    .stDateInput .react-datepicker__day--keyboard-selected,
    .stDateInput [data-baseweb="calendar"] button[aria-pressed="true"],
    .stDateInput [data-baseweb="calendar"] button[aria-label*="selected"],
    .react-datepicker__day--selected,
    .react-datepicker__day--keyboard-selected {{
      background-color: {PURPLE_HEX} !important;
      color: #ffffff !important;
    }}
    
    /* All text inside calendar */
    .stDateInput [data-baseweb="calendar"] span,
    .stDateInput [data-baseweb="datepicker"] span {{
      color: #0f172a !important;
    }}
    
    /* Hide duplicate date display below input */
    [data-testid="stDateInput"] > label + div + div {{
      display: none !important;
    }}
    [data-testid="stDateInput"] [data-testid="stMarkdownContainer"] {{
      display: none !important;
    }}
    div[data-testid="stDateInput"] + div[data-testid="stMarkdownContainer"],
    div[data-testid="stDateInput"] + div[data-testid="stText"],
    div[data-testid="stDateInput"] ~ p {{
      display: none !important;
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* SELECTBOX STYLING (PATCH 1 from tabs.py + dropdown CSS from app.py)     */
    /* ═══════════════════════════════════════════════════════════════════════ */
    
    /* Force readable text inside selectboxes */
    .stSelectbox [data-baseweb="select"] div {{
      color: #000000 !important;
    }}
    .stSelectbox [data-baseweb="popover"] {{
      max-height: 260px;
      overflow-y: auto;
      border-radius: 16px;
      box-shadow: 0 0 24px rgba(0,0,0,0.7);
    }}
    
    /* Hide autocomplete input (dropdown CSS from app.py) */
    [data-baseweb="select"] input[aria-autocomplete="list"] {{
      caret-color: transparent !important;
      pointer-events: none !important;
      user-select: none !important;
      opacity: 0 !important;
      width: 0 !important;
      min-width: 0 !important;
    }}
    
    /* Make entire select clickable */
    [data-baseweb="select"] [role="combobox"],
    [data-baseweb="select"] > div {{
      cursor: pointer !important;
    }}
    
    /* Hide default SVG chevron */
    [data-baseweb="select"] svg {{
      display: none !important;
    }}
    
    /* Add custom chevron */
    [data-baseweb="select"] > div {{
      position: relative !important;
    }}
    [data-baseweb="select"] > div::after {{
      content: "";
      position: absolute;
      right: 12px;
      top: 50%;
      transform: translateY(-50%);
      width: 16px;
      height: 16px;
      background-image: url("{chevron_svg}");
      background-repeat: no-repeat;
      background-size: 16px 16px;
      opacity: .9;
      pointer-events: none;
    }}
    
    /* Preserve normal inputs */
    [data-testid="stTextInput"] input,
    [data-testid="stPassword"] input,
    [data-testid="stTextArea"] textarea {{
      pointer-events: auto !important;
      opacity: 1 !important;
      width: 100% !important;
    }}
    
    /* Prevent popover from being cut off (PATCH 4 from tabs.py) */
    [data-baseweb="popover"] {{
      z-index: 999999 !important;
      overflow: visible !important;
    }}
    [data-baseweb="popover"] [data-baseweb="menu"] {{
      max-height: 260px !important;
      overflow-y: auto !important;
      border-radius: 16px !important;
      box-shadow: 0 0 24px rgba(0,0,0,0.30) !important;
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* SOFT BACKGROUND & LABEL FIXES (from app.py inject_soft_bg, inject_label_fix) */
    /* ═══════════════════════════════════════════════════════════════════════ */
    [data-testid="stAppViewContainer"] {{
      background: var(--ea-bg-soft) !important;
    }}
    header[data-testid="stHeader"],
    [data-testid="stToolbar"] {{
      background: var(--ea-bg-soft) !important;
      border-bottom: none !important;
      box-shadow: none !important;
    }}
    [data-testid="stSidebar"] {{
      background: #ffffff !important;
    }}
    [data-testid="stSidebar"] * {{
      color: #0f172a !important;
    }}
    
    /* Fix label colors for form inputs */
    [data-testid="stSelectbox"] label,
    [data-testid="stRadio"] label,
    [data-testid="stTextInput"] label {{
      color: #0f172a !important;
      font-weight: 600 !important;
    }}
    
    /* ═══════════════════════════════════════════════════════════════════════ */
    /* GLOBAL CSS FROM theme.py inject_global_css()                             */
    /* ═══════════════════════════════════════════════════════════════════════ */
    
    /* Lock sidebar permanently open & remove toggles */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapseControl"],
    button[aria-label="Toggle sidebar"],
    button[title="Collapse sidebar"],
    button[title="Expand sidebar"],
    header [data-testid="baseButton-headerNoPadding"],
    header [data-testid="baseButton-header"],
    [data-testid="stSidebar"] [data-testid="icon-chevron-right"],
    [data-testid="stSidebar"] [data-testid="icon-chevron-left"] {{
      display: none !important;
    }}
    
    section[data-testid="stSidebar"] {{
      width: 360px !important;
      min-width: 360px !important;
      max-width: 360px !important;
      transform: none !important;
      visibility: visible !important;
      background: var(--card) !important;
      border-right: 1px solid var(--grid) !important;
    }}
    
    /* Force all sidebar text/icons black */
    section[data-testid="stSidebar"] * {{
      color: var(--ink) !important;
    }}
    section[data-testid="stSidebar"] svg {{
      fill: var(--ink) !important;
      stroke: var(--ink) !important;
    }}
    section[data-testid="stSidebar"] .block-container {{
      padding-top: 12px;
    }}
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] legend {{
      color: var(--ink) !important;
      font-weight: 700;
    }}
    
    /* App shell (light) */
    .stApp {{
      background-color: var(--bg);
      color: var(--ink);
    }}
    .block-container {{
      padding: 18px 26px 52px 26px;
      max-width: 1400px;
    }}
    header[data-testid="stHeader"] {{
      background: var(--card) !important;
      border-bottom: 1px solid var(--grid);
    }}
    header[data-testid="stHeader"] * {{
      color: var(--ink) !important;
    }}
    div[data-testid="stToolbar"] {{
      display: none !important;
    }}
    
    /* Controls & menus (stay light on hover/focus) */
    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div,
    [data-baseweb="base-input"],
    input, textarea {{
      background: var(--card) !important;
      color: var(--ink) !important;
      border: 1px solid var(--border) !important;
      border-radius: 12px !important;
      box-shadow: none !important;
    }}
    
    /* Focus rings without darkening */
    [data-baseweb="input"]:focus-within > div,
    [data-baseweb="select"]:focus-within > div,
    input:focus, textarea:focus {{
      background: var(--card) !important;
      border-color: var(--border) !important;
      outline: none !important;
      box-shadow: 0 0 0 2px rgba(72,0,255,0.10) !important;
    }}
    
    /* Buttons */
    .stButton > button {{
      background: #ffffff !important;
      color: var(--ink) !important;
      border: 1px solid var(--border) !important;
      border-radius: 12px !important;
      box-shadow: none !important;
      transition: background .12s ease, border-color .12s ease !important;
    }}
    .stButton > button:hover,
    .stButton > button:focus {{
      background: #f9fafb !important;
      border-color: var(--border) !important;
    }}
    .stButton > button:active {{
      background: #f3f4f6 !important;
      border-color: var(--border) !important;
    }}
    
    /* Menus / popovers */
    [data-baseweb="menu"],
    [data-baseweb="popover"] [data-baseweb="menu"],
    ul[role="listbox"] {{
      background: var(--card) !important;
      color: var(--ink) !important;
      border: 1px solid var(--grid) !important;
      box-shadow: 0 8px 24px rgba(15,23,42,0.12) !important;
    }}
    [data-baseweb="menu"] [data-baseweb="menu-item"],
    ul[role="listbox"] [data-baseweb="menu-item"] {{
      background: var(--card) !important;
      color: var(--ink) !important;
    }}
    [data-baseweb="menu"] [data-baseweb="menu-item"][aria-selected="true"],
    ul[role="listbox"] [data-baseweb="menu-item"][aria-selected="true"],
    [data-baseweb="menu"] [data-baseweb="menu-item"]:hover,
    ul[role="listbox"] [data-baseweb="menu-item"]:hover {{
      background: var(--hover) !important;
      color: var(--ink) !important;
    }}
    
    /* Expander (header + open content) */
    [data-testid="stExpander"] > details {{
      background: #ffffff !important;
      border: 1px solid var(--border) !important;
      border-radius: 12px !important;
      overflow: hidden !important;
    }}
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] div[role="button"] {{
      background: #f3f4f6 !important;
      color: var(--ink) !important;
      border-bottom: 1px solid var(--border) !important;
      padding: .65rem .9rem !important;
    }}
    [data-testid="stExpander"] > details[open] > div {{
      background: #ffffff !important;
      padding: .75rem .9rem !important;
    }}
    
    /* Alerts (readable text) */
    .stAlert {{
      background: #ecfdf5 !important;
      border: 1px solid #bbf7d0 !important;
      color: #064e3b !important;
      border-radius: 12px !important;
    }}
    .stAlert * {{
      color: #064e3b !important;
    }}
    
    /* Tables / tabs / cards */
    .header-logo-wrap {{
      display: flex;
      justify-content: center;
      align-items: center;
      margin: 2px 0 8px 0;
    }}
    .header-logo-img {{
      width: clamp(240px, 22vw, 380px);
      height: auto;
      display: block;
    }}
    
    .section {{
      background: transparent;
      border: none;
      padding: 0;
      margin: 0;
      box-shadow: none;
    }}
    
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 14px;
      margin: 8px 0 18px 0;
    }}
    .kpi {{
      background: var(--card);
      border-radius: 16px;
      padding: 14px 16px;
      border: 1px solid rgba(0,0,0,0.06);
      box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }}
    .kpi .label {{
      font-size: 12px;
      color: var(--muted);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .kpi .value {{
      font-size: 28px;
      font-weight: 900;
      color: var(--accent);
      line-height: 1.2;
      margin-top: 2px;
    }}
    .muted {{
      color: var(--muted);
      font-size: 13px;
    }}
    .spacer-12 {{
      height: 12px;
    }}
    
    .stTabs [data-baseweb="tab-list"] {{
      gap: 6px;
    }}
    .stTabs [data-baseweb="tab"] {{
      color: var(--muted);
      background: var(--card);
      border-radius: 12px 12px 0 0;
      padding: 10px 14px;
      font-weight: 700;
      border: 1px solid var(--grid);
      border-bottom: none;
    }}
    .stTabs [aria-selected="true"] {{
      color: var(--accent) !important;
      background: var(--card) !important;
      box-shadow: 0 -2px 12px rgba(0,0,0,0.06);
    }}
    
    /* Chat/coach (always light) */
    .edgecoach {{
      background: #fff !important;
      color: var(--ink) !important;
      border: 1px solid var(--grid) !important;
      border-radius: 12px !important;
      padding: 12px;
    }}
    .edgecoach .stTextInput input,
    .edgecoach .stTextArea textarea {{
      background: #fff !important;
      color: var(--ink) !important;
      border-color: var(--grid) !important;
    }}
    .edgecoach .msg-user {{
      background: color-mix(in oklab, white, var(--accent) 12%);
      border: 1px solid color-mix(in oklab, var(--accent), #000 20%);
      color: var(--ink);
      border-radius: 10px;
      padding: 10px 12px;
    }}
    .edgecoach .msg-assistant {{
      background: color-mix(in oklab, white, #000 6%);
      border: 1px solid var(--grid);
      color: var(--ink);
      border-radius: 10px;
      padding: 10px 12px;
    }}
    
    /* Watermark and other common elements */
    .live-banner {{
      background: color-mix(in oklab, {PURPLE_HEX}, white 85%);
      color: {PURPLE_HEX};
      padding: 8px 16px;
      border-radius: 12px;
      text-align: center;
      font-weight: 700;
      margin-bottom: 16px;
      border: 1px solid color-mix(in oklab, {PURPLE_HEX}, white 70%);
    }}
    
    .ea-empty-wrap {{
      text-align: center;
      padding: 60px 20px;
    }}
    .ea-empty-title {{
      font-size: 24px;
      font-weight: 700;
      color: var(--muted);
      margin-bottom: 20px;
    }}
    .ea-empty-btn {{
      max-width: 400px;
      margin: 0 auto;
    }}
    
    .ea-watermark {{
      text-align: center;
      opacity: 0.3;
      margin-top: 40px;
      padding: 20px;
    }}
    .ea-watermark img {{
      max-width: 180px;
      height: auto;
    }}


    /* ══════════════════════════════════════════════════════════════════════ */
    /* SLIDER — default Streamlit track (already purple via primaryColor);
       just a soft ring on the thumb. Tick labels + value bubble hidden elsewhere. */
    [data-testid="stSlider"] [role="slider"] {{
        box-shadow: 0 0 0 3px rgba(72,0,255,0.12) !important;
    }}

    /* ══════════════════════════════════════════════════════════════════════ */
    /* RADIO BUTTONS — visible, clickable, purple selected state              */
    /* ══════════════════════════════════════════════════════════════════════ */

    /* Outer ring — grey border, transparent bg (unselected default) */
    [data-testid="stRadio"] [data-baseweb="radio"] > div:first-child {{
        border: 2px solid #d1d5db !important;
        background-color: transparent !important;
        flex-shrink: 0 !important;
        border-radius: 50% !important;
    }}
    /* Inner dot — hidden by default */
    [data-testid="stRadio"] [data-baseweb="radio"] > div:first-child > div {{
        background-color: transparent !important;
        opacity: 0 !important;
    }}
    /* Selected state via :has() — outer ring solid purple */
    [data-testid="stRadio"] [data-baseweb="radio"]:has(input:checked) > div:first-child {{
        border-color: {PURPLE_HEX} !important;
        background-color: {PURPLE_HEX} !important;
    }}
    /* Selected state — inner dot white (ring-with-dot look) */
    [data-testid="stRadio"] [data-baseweb="radio"]:has(input:checked) > div:first-child > div {{
        background-color: #ffffff !important;
        opacity: 1 !important;
    }}
    /* Make sure the label/text area next to the dot has NO background */
    [data-testid="stRadio"] label {{
        background: transparent !important;
    }}
    /* Ensure radio labels are visible, dark, and clickable */
    [data-testid="stRadio"] label,
    [data-testid="stRadio"] label p,
    [data-testid="stRadio"] label span {{
        color: #0f172a !important;
        pointer-events: auto !important;
        cursor: pointer !important;
    }}
    /* Restore pointer events on the hidden radio input */
    [data-testid="stRadio"] input[type="radio"] {{
        position: absolute !important;
        opacity: 0 !important;
        pointer-events: auto !important;
        width: 100% !important;
        height: 100% !important;
        cursor: pointer !important;
        margin: 0 !important;
    }}
    [data-testid="stRadio"] [data-baseweb="radio"] {{
        position: relative !important;
        cursor: pointer !important;
    }}

    /* ══════════════════════════════════════════════════════════════════════ */
    /* INPUT CARD BOXES — white bg, purple border, white input field          */
    /* ══════════════════════════════════════════════════════════════════════ */

    div[data-testid="stNumberInput"] {{
        background: #ffffff !important;
        border: 1px solid #e8e0ff !important;
        border-radius: 12px !important;
        padding: 12px 14px 14px 14px !important;
        margin-bottom: 8px !important;
        overflow: hidden !important;
    }}
    div[data-testid="stSlider"] {{
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }}
    div[data-testid="stNumberInput"] label {{
        color: #0f172a !important;
        font-weight: 600 !important;
        font-size: 13px !important;
    }}
    /* Number input field itself — white background */
    div[data-testid="stNumberInput"] input {{
        background: #ffffff !important;
        color: #0f172a !important;
    }}
    /* +/- stepper buttons — white background, dark icon */
    div[data-testid="stNumberInput"] button {{
        background: #ffffff !important;
        color: #0f172a !important;
        border-color: #e5e7eb !important;
    }}

    /* Hidden JS helper components must take no space (white strips fix) */
    iframe[title="streamlit_js_eval.streamlit_js_eval"] {{ display: none !important; }}
    div[data-testid="stElementContainer"]:has(> iframe[title="streamlit_js_eval.streamlit_js_eval"]) {{
      display: none !important; height: 0 !important; margin: 0 !important;
    }}
    div[data-testid="stCustomComponentV1"] {{ background: transparent !important; }}

    /* Sidebar rhythm */
    [data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {{ gap: 0.6rem !important; }}

    /* Page chrome: no decoration strip, transparent header, no footer/badge */
    [data-testid="stDecoration"] {{ display: none !important; }}
    [data-testid="stHeader"], .stAppHeader {{ display: none !important; }}
    [data-testid="stSidebar"] > div:first-child {{ padding-top: 1.5rem !important; }}
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {{
        display: none !important;
    }}

    /* Typography scale: tighter, more modern headings */
    .stMarkdown h1 {{ font-size: 26px !important; font-weight: 800 !important; letter-spacing: -0.02em; }}
    .stMarkdown h2 {{ font-size: 21px !important; font-weight: 800 !important; letter-spacing: -0.015em; }}
    .stMarkdown h3 {{ font-size: 19px !important; font-weight: 800 !important; letter-spacing: -0.01em; color: #0f172a; margin-bottom: 0 !important; }}
    .stMarkdown h4 {{ font-size: 15px !important; font-weight: 700 !important; color: #334155; }}

    /* Filters popover trigger: white pill */
    [data-testid="stPopover"] > div > button, [data-testid="stPopoverButton"] {{
        background: #ffffff !important;
        border: 1px solid rgba(0,0,0,0.08) !important;
        border-radius: 999px !important;
        padding: 6px 18px !important;
        font-weight: 600 !important;
        color: #334155 !important;
        box-shadow: 0 2px 10px rgba(0,0,0,0.04) !important;
    }}
    .ea-topbar-logo img {{ width: 170px !important; height: auto; display: block; }}
    div[data-testid="stAlert"] {{ border-radius: 12px !important; }}
    div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]),
    div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]),
    div[data-testid="stAlert"]:has(svg[title="Info"]) {{
        background: #f8fafc !important;
        border: 1px solid #eef0f5 !important;
        color: #64748b !important;
    }}
    div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) p,
    div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) p {{
        color: #64748b !important;
    }}
    section.main div[data-testid="stVerticalBlock"],
    [data-testid="stMain"] div[data-testid="stVerticalBlock"] {{ gap: 0.75rem !important; }}
    [data-testid="stStatusWidget"] {{ visibility: hidden !important; }}
    #MainMenu {{ visibility: hidden !important; }}
    footer {{ visibility: hidden !important; height: 0 !important; }}
    [data-testid="stBottom"] {{ background: transparent !important; }}
    .viewerBadge_container__r5tak, [class*="viewerBadge"] {{ display: none !important; }}

    /* Sliders: clean track only — no min/max labels, no value bubble */
    [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {{ display: none !important; }}
    [data-testid="stSliderThumbValue"] {{ display: none !important; }}

    /* Dividers: soft and quiet */
    hr {{ border: none !important; border-top: 1px solid #f1f5f9 !important; margin: 26px 0 !important; }}

    /* Content width: don't stretch across huge monitors */
    section.main div.block-container,
    [data-testid="stMainBlockContainer"] {{
        max-width: 1200px !important;
        margin: 0 auto !important;
    }}

    /* Tight vertical rhythm for settings rows inside expanders */
    div[data-testid="stExpander"] div[data-testid="stVerticalBlock"] {{
        gap: 0.4rem !important;
    }}

    /* Expanders styled like cards (no hollow outline look) */
    div[data-testid="stExpander"] > details {{
      background: #ffffff !important;
      border: 1px solid rgba(0,0,0,0.06) !important;
      border-radius: 12px !important;
      box-shadow: 0 2px 10px rgba(0,0,0,0.04) !important;
    }}
    div[data-testid="stExpander"] summary {{
      font-weight: 600 !important;
      color: #334155 !important;
    }}

    /* Sidebar: cleaner separation and tighter rhythm */
    [data-testid="stSidebar"] {{
      border-right: 1px solid rgba(0,0,0,0.06);
    }}
    [data-testid="stSidebar"] .stSelectbox label p {{
      font-size: 12px !important;
      font-weight: 600 !important;
      color: #64748b !important;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}

    /* Tables: swipeable on phones, essentials-only under 640px */
    .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
    @media (max-width: 640px) {{
        .table-wrap th:nth-child(4), .table-wrap td:nth-child(4),
        .table-wrap th:nth-child(5), .table-wrap td:nth-child(5),
        .table-wrap th:nth-child(6), .table-wrap td:nth-child(6) {{
            display: none;
        }}
        .table-wrap th, .table-wrap td {{
            font-size: 13px !important;
            padding: 8px 10px !important;
        }}
    }}

    /* While rerunning, fully remove the stale previous render so duplicate
       tab strips / ghosts never paint (visibility:hidden still reserved
       layout space and left faded strips). */
    .stApp[data-test-script-state="running"] [data-stale="true"] {{
        opacity: 0.35 !important;
        transition: none !important;
    }}
    .stApp[data-test-script-state="running"] div[data-stale="true"][data-testid="stTabs"],
    .stApp[data-test-script-state="running"] [data-stale="true"] [data-baseweb="tab-list"],
    .stApp[data-test-script-state="running"] [data-stale="true"] iframe {{
        display: none !important;
    }}

    /* Kill the rerun cross-fade entirely: no half-transparent ghost frame
       while Streamlit swaps old render for new. */
    [data-testid="stAppViewContainer"] .element-container,
    [data-testid="stVerticalBlock"], [data-testid="stMarkdown"],
    .stTabs, [data-baseweb="tab-panel"] {{
        transition: none !important;
        animation: none !important;
    }}
    [data-testid="stAppViewContainer"] {{ opacity: 1 !important; }}
    .stTabs, .stTabs [data-baseweb="tab-list"], .stTabs button[role="tab"],
    div[data-testid="stTabs"]:not([data-stale="true"]) {{
        opacity: 1 !important;
        filter: none !important;
    }}

    /* Bordered st.container = house card */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: #ffffff;
        border: 1px solid #eef0f4 !important;
        border-radius: 16px;
        padding: 18px 22px 20px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        margin: 6px 0 18px;
    }}

    /* No copy-link icons on heading hover */
    [data-testid="stHeaderActionElements"] {{ display: none !important; }}
    h1 > a, h2 > a, h3 > a, h4 > a {{ display: none !important; }}

    /* Tab underline: only under the tabs, not the full page width */
    .stTabs [data-baseweb="tab-border"] {{ display: none !important; }}

    /* Filters popover: comfortable panel, no edge-cramping */
    [data-testid="stPopoverBody"] {{
        min-width: 400px !important;
        max-width: 460px !important;
        max-height: 78vh !important;
        overflow-y: auto !important;
        padding: 14px 16px !important;
        border-radius: 12px !important;
    }}

    /* Mobile: hint that the tab row scrolls */
    @media (max-width: 640px) {{
        .stTabs [data-baseweb="tab-list"] {{
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
            padding-right: 28px !important;
            mask-image: linear-gradient(to right, black 92%, transparent 100%);
            -webkit-mask-image: linear-gradient(to right, black 92%, transparent 100%);
        }}
    }}

    /* Radios as pills (Most Possible / Worst / Best etc.) */
    [data-testid="stRadio"] [role="radiogroup"] {{ gap: 8px !important; }}
    [data-testid="stRadio"] [role="radiogroup"] > label {{
        border: 1px solid rgba(0,0,0,0.10) !important;
        border-radius: 999px !important;
        padding: 5px 16px 5px 10px !important;
        background: #ffffff;
        transition: none;
    }}
    [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) {{
        background: #4800ff !important;
        border-color: #4800ff !important;
    }}
    [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) p,
    [data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) span {{
        color: #ffffff !important;
    }}
    [data-testid="stRadio"] [data-baseweb="radio"] > div:first-child {{
        display: none !important;
    }}

    /* If two tab strips ever coexist mid-rerun, hide the older sibling */
    div[data-testid="stTabs"]:has(~ div[data-testid="stTabs"]) {{ display: none !important; }}

    /* Inside forms, dragging needs feedback before Run is pressed */
    [data-testid="stForm"] [data-testid="stSliderThumbValue"] {{
        display: block !important;
        font-family: "Source Sans Pro", -apple-system, sans-serif !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        background: #4800ff !important;
        color: #ffffff !important;
        padding: 1px 9px !important;
        border-radius: 999px !important;
        top: -26px !important;
    }}
    [data-testid="stForm"] {{ border: none !important; padding: 0 !important; }}

    /* Tabs as pills */
    .stTabs [data-baseweb="tab-list"] {{ gap: 8px !important; }}
    .stTabs button[role="tab"] {{
        background: #ffffff !important;
        border: 1px solid rgba(0,0,0,0.06) !important;
        border-radius: 999px !important;
        padding: 4px 18px !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.03) !important;
    }}
    .stTabs button[role="tab"] p {{ color: #64748b !important; font-weight: 600 !important; }}
    .stTabs button[role="tab"][aria-selected="true"] {{
        background: #4800ff !important;
        border-color: #4800ff !important;
    }}
    .stTabs button[role="tab"][aria-selected="true"] p {{ color: #ffffff !important; }}
    .stTabs [data-baseweb="tab-highlight"] {{ display: none !important; }}

    </style>
    """, unsafe_allow_html=True)




def inject_dark_overlay():
    """Dark theme overlay. Injected after the base (light) theme when the user
    picks dark mode — !important rules override the light inline styles.
    Charts and data tables intentionally stay as white cards for legibility."""
    st.markdown("""
    <style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
    [data-testid="stHeader"], .stAppHeader, [data-testid="stToolbar"] {
        background: #0e1117 !important;
    }
    div[style*="background: rgb(255, 255, 255)"] {
        background: #161b27 !important;
        border-color: rgba(255,255,255,0.09) !important;
    }
    div[style*="background: rgb(248, 249, 252)"], div[style*="background: rgb(248, 250, 252)"] {
        background: #1d2331 !important;
    }
    div[style*="background: rgb(238, 240, 245)"] { background: #262c3b !important; }
    div[style*="background: rgb(240, 235, 255)"] {
        background: #251d42 !important;
        color: #d8d2f0 !important;
    }
    div[style*="background: rgb(232, 247, 238)"] { background: #143323 !important; }
    div[style*="border-top: 2px solid rgb(238, 240, 245)"] { border-color: #232937 !important; }
    [style*="color: rgb(15, 23, 42)"] { color: #e8ebf1 !important; }
    [style*="color: rgb(51, 65, 85)"] { color: #c9d0dc !important; }
    [style*="color: rgb(100, 116, 139)"] { color: #9aa4b4 !important; }
    .stMarkdown, .stMarkdown p, .stMarkdown li { color: #d3d9e3 !important; }
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 { color: #eef1f6 !important; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
        color: #8791a1 !important;
    }
    .kpi { background: #161b27 !important; border-color: rgba(255,255,255,0.09) !important; }
    .kpi .label { color: #8791a1 !important; }
    .kpi .value { color: #e8ebf1; }
    .kpi .muted { color: #8791a1 !important; }
    hr { border-top-color: #232937 !important; }
    [data-baseweb="select"] > div, [data-baseweb="input"] > div,
    [data-baseweb="base-input"], input, textarea {
        background: #161b27 !important;
        color: #e8ebf1 !important;
        border-color: rgba(255,255,255,0.12) !important;
    }
    ul[role="listbox"], [data-baseweb="menu"], [data-baseweb="popover"] > div,
    [data-baseweb="popover"] > div > div, [data-baseweb="popover"] ul,
    [data-testid="stSelectboxVirtualDropdown"],
    [data-testid="stSelectboxVirtualDropdown"] ul,
    [data-testid="stSelectboxVirtualDropdown"] > div {
        background: #161b27 !important;
    }
    ul[role="listbox"] li, [role="option"] { color: #d3d9e3 !important; }
    div[data-testid="stExpander"] > details, [data-testid="stPopoverBody"] {
        background: #141926 !important;
        border-color: rgba(255,255,255,0.09) !important;
    }
    div[data-testid="stExpander"] summary { color: #c9d0dc !important; }
    [data-testid="stPopover"] > div > button, [data-testid="stPopoverButton"],
    .stButton button {
        background: #161b27 !important;
        border-color: rgba(255,255,255,0.12) !important;
        color: #c9d0dc !important;
    }
    div[data-testid="stNumberInput"] {
        background: #161b27 !important;
        border-color: rgba(255,255,255,0.09) !important;
    }
    div[data-testid="stNumberInput"] label, div[data-testid="stSlider"] label,
    [data-testid="stSelectbox"] label, [data-testid="stDateInput"] label,
    [data-testid="stWidgetLabel"] p {
        color: #9aa4b4 !important;
    }
    .stTabs button[role="tab"] {
        background: #161b27 !important;
        border-color: rgba(255,255,255,0.09) !important;
    }
    .stTabs button[role="tab"] p { color: #9aa4b4 !important; }
    .stTabs button[role="tab"][aria-selected="true"] { background: #4800ff !important; }
    .stTabs button[role="tab"][aria-selected="true"] p { color: #ffffff !important; }
    div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) {
        background: #141926 !important;
        border-color: rgba(255,255,255,0.09) !important;
        color: #9aa4b4 !important;
    }
    [data-testid="stRadio"] label, [data-testid="stRadio"] label p,
    [data-testid="stRadio"] label span {
        color: #c9d0dc !important;
    }
    .entry-card, .table-wrap, .table-wrap table {
        background: #161b27 !important;
        border-color: rgba(255,255,255,0.09) !important;
    }
    .table-wrap th {
        background: #1d2331 !important;
        color: #c9d0dc !important;
        border-color: rgba(255,255,255,0.10) !important;
    }
    .table-wrap td {
        background: transparent !important;
        color: #c9d0dc !important;
        border-color: rgba(255,255,255,0.06) !important;
    }
    .table-wrap tr:nth-child(even) td { background: #191f2c !important; }
    .ref-card {
        background: #161b27 !important;
        border-top-color: rgba(255,255,255,0.09) !important;
        border-right-color: rgba(255,255,255,0.09) !important;
        border-bottom-color: rgba(255,255,255,0.09) !important;
        /* left border keeps its semantic green/red/purple stripe */
    }
    .ref-card-title { color: #e8ebf1 !important; }
    .ref-card-body { color: #9aa4b4 !important; }
    .proj-stat-cell { background: #161b27 !important; border-color: rgba(255,255,255,0.09) !important; }
    .proj-stat-label { color: #9aa4b4 !important; }
    .proj-stat-value { color: #e8ebf1; }
    .proj-table-row { background: #161b27 !important; color: #c9d0dc !important; }
    .proj-table-row:nth-child(even) { background: #191f2c !important; }
    .stSelectbox [data-baseweb="select"] div {
        background: #161b27 !important;
        color: #e8ebf1 !important;
    }
    [data-baseweb="select"] > div:focus-within,
    [data-baseweb="select"] [aria-expanded="true"] {
        background: #161b27 !important;
    }
    .ea-title { color: #eef1f6 !important; }
    .ea-sub, .ea-help, .ea-step { color: #9aa4b4 !important; }
    .ea-secondary .stButton > button {
        background: #161b27 !important;
        color: #c9d0dc !important;
        border-color: rgba(255,255,255,0.12) !important;
    }
    [style*="color: rgb(17, 24, 39)"] { color: #e8ebf1 !important; }
    [style*="color: rgb(71, 85, 105)"] { color: #9aa4b4 !important; }
    [style*="color: rgb(30, 41, 59)"] { color: #dfe4ec !important; }
    div[role="dialog"], [data-testid="stDialog"] > div > div {
        background: #141926 !important;
        border-color: rgba(255,255,255,0.09) !important;
    }
    div[role="dialog"] p, div[role="dialog"] h1, div[role="dialog"] h2,
    div[role="dialog"] h3, div[role="dialog"] span {
        color: #d3d9e3 !important;
    }
    div[role="dialog"] div[style*="color: rgb(51, 65, 85)"] { color: #c9d0dc !important; }
    [data-baseweb="calendar"], [data-baseweb="datepicker"] {
        background: #161b27 !important;
        color: #d3d9e3 !important;
    }
    [data-baseweb="calendar"] button { color: #d3d9e3 !important; }
    li[role="option"]:hover, [data-baseweb="menu"] [aria-selected="true"] {
        background: #232a3a !important;
    }
    .stCode, pre, code {
        background: #10141d !important;
        color: #c9d0dc !important;
    }
    [data-testid="stSpinner"] p { color: #9aa4b4 !important; }
    .stButton button:hover, .stButton button:focus, .stButton button:active,
    [data-testid="stPopover"] > div > button:hover,
    [data-testid="stPopover"] > div > button:focus,
    [data-testid="stPopoverButton"]:hover {
        background: #1d2331 !important;
        color: #e8ebf1 !important;
        border-color: rgba(255,255,255,0.2) !important;
    }
    .stButton button:hover p, [data-testid="stPopover"] > div > button:hover p {
        color: #e8ebf1 !important;
    }
    .stTabs button[role="tab"]:hover { background: #1d2331 !important; }
    .stTabs button[role="tab"]:hover p { color: #e8ebf1 !important; }
    .stTabs button[role="tab"][aria-selected="true"]:hover { background: #4800ff !important; }
    .stTabs button[role="tab"][aria-selected="true"]:hover p { color: #ffffff !important; }
    ul[role="listbox"] li:hover, [role="option"]:hover,
    [data-baseweb="menu"] li:hover {
        background: #232a3a !important;
    }
    ul[role="listbox"] li, [data-baseweb="menu"] li, [role="option"],
    [data-testid="stSelectboxVirtualDropdown"] li {
        color: #e8ebf1 !important;
        background: #161b27 !important;
    }
    ul[role="listbox"] li *, [data-baseweb="menu"] li *, [role="option"] *,
    [data-testid="stSelectboxVirtualDropdown"] li * {
        color: #e8ebf1 !important;
        background: transparent !important;
    }
    ul[role="listbox"] li:hover, [data-baseweb="menu"] li:hover, [role="option"]:hover,
    [data-testid="stSelectboxVirtualDropdown"] li:hover,
    ul[role="listbox"] li[aria-selected="true"], [role="option"][aria-selected="true"],
    [role="option"][data-highlighted], ul[role="listbox"] li:focus {
        background: #262f42 !important;
        color: #ffffff !important;
    }
    ul[role="listbox"] [aria-selected="true"],
    [data-testid="stSelectboxVirtualDropdown"] [aria-selected="true"] {
        background: #232a3a !important;
    }
    div[data-testid="stAlert"] p, div[data-testid="stAlert"] span,
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] * {
        color: #9aa4b4 !important;
    }
    button[data-testid="stBaseButton-secondary"],
    button[kind="secondary"], button[kind="secondaryFormSubmit"] {
        background: #161b27 !important;
        color: #c9d0dc !important;
        border-color: rgba(255,255,255,0.12) !important;
    }
    button[data-testid="stBaseButton-secondary"]:hover,
    button[kind="secondary"]:hover {
        background: #1d2331 !important;
        color: #e8ebf1 !important;
    }
    [data-baseweb="select"]:hover > div, [data-baseweb="select"] > div:hover {
        background: #161b27 !important;
        color: #e8ebf1 !important;
        border-color: rgba(255,255,255,0.2) !important;
    }
    div[data-testid="stExpander"] summary:hover {
        background: #1d2331 !important;
        color: #e8ebf1 !important;
    }
    .stTabs [data-baseweb="tab-list"] { background: transparent !important; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: #161b27 !important;
        border-color: rgba(255,255,255,0.09) !important;
    }
    .ea-pb-lab { color: #e5e7eb !important; }
    .ea-pb-n { color: #6b7280 !important; }
    .ea-pb-track { background: #1a1f2b !important; }
    .ea-pb-zero { border-left-color: #3a4356 !important; }
    .ea-et { background: #161b27 !important; border-color: rgba(255,255,255,0.09) !important; }
    .ea-et-lab { color: #9aa3b5 !important; }
    .ea-et-meter { background: #232937 !important; }
    .ea-et-meta { color: #6b7280 !important; }
    .ea-ew-hub { fill: #1a1f2b !important; }
    .ea-ew-hublab { fill: #8b94a3 !important; }
    .ea-ew-name { fill: #8b94a3 !important; }
    </style>
    """, unsafe_allow_html=True)


# ───────────────────────── Favicon helpers ─────────────────────────
def _square_canvas(im: Image.Image, size: int = 256) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    im = im.copy()
    im.thumbnail((size-8, size-8), Image.LANCZOS)
    x = (size - im.width)//2
    y = (size - im.height)//2
    canvas.paste(im, (x, y), im)
    return canvas


def setup_favicon():
    """Set up the favicon in browser tab."""
    try:
        if RAW_ICON.exists():
            im = Image.open(RAW_ICON).convert("RGBA")
            im = _square_canvas(im, 256)
            im.save(FAVI_PNG, optimize=True)
        png = FAVI_PNG if FAVI_PNG.exists() else RAW_ICON
        if not png.exists():
            return
        b64 = base64.b64encode(png.read_bytes()).decode()
        components.html(
            f"""
            <script>
            (function(){{
              const href = "data:image/png;base64,{b64}";
              const rels = ["icon","shortcut icon"];
              rels.forEach(r => {{
                let link = document.querySelector(`link[rel="${{r}}"]`);
                if (!link) {{
                  link = document.createElement('link');
                  link.rel = r;
                  document.head.appendChild(link);
                }}
                link.type = 'image/png';
                link.href = href;
              }});
            }})();
            </script>
            """,
            height=0, width=0
        )
    except Exception:
        pass


# ───────────────────────── Header (light logo) ────────────────────
def _img_tag_from_file(path: Path) -> str:
    try:
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"<img class='header-logo-img' src='data:image/png;base64,{b64}' alt='Edge Analysis'/>"
    except Exception:
        return ""


def inject_header_bar(status_text: str = "", status_ok: bool = True):
    """Compact top bar: logo left, connection pill right. Logo follows the theme."""
    _dark = st.session_state.get("ea_theme_pref") == "dark"
    if _dark and HEADER_LOGO_DARK.exists():
        logo_path = HEADER_LOGO_DARK
    else:
        logo_path = HEADER_LOGO_LIGHT if HEADER_LOGO_LIGHT.exists() else HEADER_LOGO_DARK
    logo = _img_tag_from_file(logo_path) if logo_path and logo_path.exists() else ""
    pill = ""
    if status_text:
        col = "#16a34a" if status_ok else "#ef4444"
        pill = (
            "<div style='display:flex;align-items:center;gap:8px;background:#ffffff;"
            "border:1px solid rgba(0,0,0,0.06);border-radius:999px;padding:8px 16px;"
            "box-shadow:0 2px 10px rgba(0,0,0,0.04);font-size:13px;font-weight:600;color:#334155;'>"
            f"<span style='width:8px;height:8px;border-radius:50%;background:{col};display:inline-block;'></span>"
            f"{status_text}</div>"
        )
    st.markdown(
        "<div class='ea-topbar' style='display:flex;justify-content:space-between;"
        "align-items:center;gap:16px;margin:0 0 14px;'>"
        f"<div class='ea-topbar-logo'>{logo}</div>{pill}</div>",
        unsafe_allow_html=True,
    )


def inject_header(_theme_ignored: str = "light"):
    """Inject centered Edge Analysis logo header."""
    logo_path = HEADER_LOGO_LIGHT if HEADER_LOGO_LIGHT.exists() else HEADER_LOGO_DARK
    if logo_path and logo_path.exists():
        st.markdown(
            f"""
            <div style="display:flex; justify-content:center; margin: 0.25rem 0 0.5rem;">
                {_img_tag_from_file(logo_path)}
            </div>
            """,
            unsafe_allow_html=True,
        )


# ───────────────────────── Chart styling helper ───────────────────
_DARK_CHART_COLORS = {
    "#eef0f5": "#252b3a",
    "#f1f5f9": "#232937",
    "#0f172a": "#dfe4ec",
    "#334155": "#c9d0dc",
    "#64748b": "#9aa4b4",
    "#cbd5e1": "#414b61",
    "#e5e7eb": "#414b61",
    "#ffffff": "#161b27",
    "#fff": "#161b27",
}


def get_chart_styler():
    """
    Return a chart styling function for Altair charts.
    Light: white canvas. Dark: dark canvas + in-spec colors remapped so
    labels/grids/rules stay legible.
    """
    c = LIGHT
    if st.session_state.get("ea_theme_pref") != "dark":
        def _styler(chart):
            return chart.configure(background=c["chart_bg"]).configure_view(fill=c["chart_bg"])
        return _styler

    import json as _json

    def _styler(chart):
        try:
            s = _json.dumps(chart.to_dict())
            for k, v in _DARK_CHART_COLORS.items():
                s = s.replace('"' + k + '"', '"' + v + '"')
            chart = chart.__class__.from_dict(_json.loads(s))
        except Exception:
            pass
        return (chart.configure(background="#161b27")
                .configure_view(fill="#161b27", stroke=None)
                .configure_axis(domainColor="#2c3242", gridColor="#232937",
                                labelColor="#8b94a3", titleColor="#8b94a3",
                                tickColor="#2c3242"))
    return _styler

# ---------------------------------------------------------------------------
# Compatibility functions for legacy references
# These functions provide backward compatibility for old code that used
# apply_theme() and inject_global_css(). The consolidated theme uses
# inject_theme() and get_chart_styler(), so apply_theme simply invokes
# inject_theme and returns the chart styler. inject_global_css is a
# no-op because all global CSS is injected via inject_theme().

def apply_theme():
    """
    Backward-compatible wrapper for legacy apply_theme().

    This function calls inject_theme() to inject all CSS and returns
    the chart styler returned by get_chart_styler().
    """
    inject_theme()
    return get_chart_styler()


def inject_global_css():
    """
    Backward-compatible no-op for legacy inject_global_css().

    All CSS is already injected via inject_theme(). This function exists
    to avoid breaking imports in older code.
    """
    # CSS is consolidated in inject_theme(); no additional action needed.
    return None
