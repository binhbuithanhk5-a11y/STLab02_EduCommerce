"""Gradio dashboard: chart (left) next to execution table (right), filter by REQ / status.
Run after test_runner.py has produced reports/test_execution.csv."""
import sys
import gradio as gr
import matplotlib.pyplot as plt
import pandas as pd

REPORT = 'reports/test_execution.csv'
STATUSES = ['PASS', 'FAIL', 'BLOCKED']
COLORS = ['#16a34a', '#dc2626', '#f59e0b']
report_df = pd.read_csv(REPORT, dtype=str).fillna('')


def dashboard_view(req='ALL', status='ALL'):
    df = report_df.copy()
    if req != 'ALL': df = df[df.requirement_id == req]
    if status != 'ALL': df = df[df.execution_status == status]
    summary = df.execution_status.value_counts().reindex(STATUSES, fill_value=0)
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(summary.index, summary.values, color=COLORS)
    ax.bar_label(bars, padding=3)
    ax.set_title('Test execution results'); ax.set_ylabel('Test cases')
    ax.set_ylim(0, max(2, int(summary.max()) + 2)); fig.tight_layout()
    cols = ['test_case_id', 'requirement_id', 'condition_id', 'scenario_id', 'expected_json',
            'actual_result', 'execution_status', 'executed_at']
    rate = round(100 * summary.PASS / len(df), 1) if len(df) else 0
    line = (f"Run: {report_df.run_id.iloc[0]} | Executed: {len(df)} | PASS: {summary.PASS} | "
            f"FAIL: {summary.FAIL} | BLOCKED: {summary.BLOCKED} | Pass rate: {rate}%")
    return fig, df[cols], line


with gr.Blocks(title='EduCommerce - STLab02 Test Dashboard') as demo:
    gr.Markdown('# EduCommerce — Requirement Traceability & Test Results')
    with gr.Row():
        req_filter = gr.Dropdown(['ALL'] + sorted(report_df.requirement_id.unique()), value='ALL', label='Requirement')
        status_filter = gr.Dropdown(['ALL'] + STATUSES, value='ALL', label='Test status')
    status_line = gr.Markdown()
    with gr.Row(equal_height=True):
        with gr.Column(scale=1, min_width=300):
            chart = gr.Plot(label='Result distribution')
        with gr.Column(scale=2, min_width=420):
            table = gr.Dataframe(label='Test execution details', interactive=False, wrap=True)
    gr.File(value='reports/test_report.xlsx', label='Download Excel report')
    outputs = [chart, table, status_line]
    req_filter.change(dashboard_view, [req_filter, status_filter], outputs)
    status_filter.change(dashboard_view, [req_filter, status_filter], outputs)
    demo.load(dashboard_view, [req_filter, status_filter], outputs)

if __name__ == '__main__':
    # share=True creates a temporary *.gradio.live link (Colab); do not share sensitive data.
    demo.launch(share='--share' in sys.argv)
