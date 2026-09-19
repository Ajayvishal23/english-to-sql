"""CSS for the Streamlit interface (works in light and dark themes)."""

CSS = """
<style>
:root {
  --t2s-accent: #4F46E5;
  --t2s-accent-2: #7C3AED;
  --t2s-ok: #059669;
  --t2s-warn: #D97706;
  --t2s-bad: #DC2626;
  --t2s-border: rgba(127, 127, 127, .22);
  --t2s-soft: rgba(79, 70, 229, .07);
}
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1180px;}
#MainMenu, footer {visibility: hidden;}
[data-testid="stToolbar"] {right: .5rem;}

/* ---------- hero ---------- */
.t2s-hero {
  background: linear-gradient(120deg, var(--t2s-accent) 0%, var(--t2s-accent-2) 100%);
  border-radius: 18px; padding: 22px 26px; color: #fff; margin-bottom: 14px;
  box-shadow: 0 10px 30px -12px rgba(79, 70, 229, .55);
}
.t2s-hero h1 {color: #fff; font-size: 1.9rem; margin: 0; padding: 0; line-height: 1.2;}
.t2s-hero p {color: rgba(255,255,255,.88); margin: 6px 0 0 0; font-size: 1rem;}
.t2s-hero .t2s-tags {margin-top: 12px;}
.t2s-hero .t2s-tag {
  display: inline-block; font-size: .75rem; padding: 3px 10px; margin: 0 6px 4px 0;
  border-radius: 999px; background: rgba(255,255,255,.18); color: #fff;
  border: 1px solid rgba(255,255,255,.28);
}

/* ---------- status cards ---------- */
.t2s-stats {display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px; margin: 4px 0 16px 0;}
.t2s-stat {border: 1px solid var(--t2s-border); border-radius: 14px; padding: 10px 14px;
  background: var(--t2s-soft);}
.t2s-stat .lbl {font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; opacity: .65;}
.t2s-stat .val {font-weight: 600; font-size: .98rem; margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.t2s-dot {display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 6px; vertical-align: middle;}
.t2s-dot.ok {background: var(--t2s-ok);}
.t2s-dot.warn {background: var(--t2s-warn); animation: t2s-pulse 1.4s infinite;}
.t2s-dot.bad {background: var(--t2s-bad);}
@keyframes t2s-pulse {0%,100% {opacity: 1;} 50% {opacity: .3;}}

/* ---------- step headings ---------- */
.t2s-step {display: flex; align-items: center; gap: 10px; margin: 18px 0 6px 0;}
.t2s-step .num {width: 26px; height: 26px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: .85rem; font-weight: 700;
  color: #fff; background: linear-gradient(120deg, var(--t2s-accent), var(--t2s-accent-2));}
.t2s-step .title {font-size: 1.12rem; font-weight: 650;}
.t2s-step .hint {font-size: .85rem; opacity: .6;}

/* ---------- badges ---------- */
.t2s-badge {display: inline-block; font-size: .78rem; font-weight: 600; padding: 2px 10px;
  border-radius: 999px; margin: 2px 0 6px 0;}
.t2s-badge.ok {background: rgba(5,150,105,.12); color: var(--t2s-ok);}
.t2s-badge.bad {background: rgba(220,38,38,.12); color: var(--t2s-bad);}
.t2s-badge.info {background: var(--t2s-soft); color: var(--t2s-accent);}

/* ---------- widgets ---------- */
div[data-testid="stTextArea"] textarea {font-size: 1rem;}
.st-key-sql_editor textarea {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
  font-size: .92rem !important;
}
div[data-testid="stMetric"] {border: 1px solid var(--t2s-border); border-radius: 12px;
  padding: 8px 14px; background: var(--t2s-soft);}
button[kind="primary"] {border-radius: 10px;}
div[data-testid="stExpander"] details {border-radius: 12px;}
section[data-testid="stSidebar"] .t2s-side-title {font-size: 1.25rem; font-weight: 700;
  margin: 0 0 2px 0;}
.t2s-empty {text-align: center; padding: 28px 10px; border: 1px dashed var(--t2s-border);
  border-radius: 14px; opacity: .8;}
.t2s-footer {text-align: center; font-size: .8rem; opacity: .55; margin-top: 36px;}
</style>
"""
