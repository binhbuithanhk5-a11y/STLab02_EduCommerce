# STLab02 – EduCommerce Test Case Execution

Bài thực hành Software Testing: phân tích requirement → test condition → test scenario → test case → **thực thi tự động bằng Python từ CSV/Excel** → report CSV/Excel/HTML + dashboard Gradio.

- Ứng dụng kiểm thử: `ecommerce_app.py` (giữ **nguyên** mã nguồn từ STLab02 Instruction – không sửa bug).
- REQ đã chọn (không trùng REQ-06/08/11): **REQ-02, REQ-04, REQ-07, REQ-09, REQ-10, REQ-15, REQ-16** (7 REQ, 7 module).
- Kết quả lần chạy tham chiếu: **38 test case – 34 PASS / 4 FAIL / 0 BLOCKED** (pass rate 89.5%, REQ coverage 7/7).

## Cấu trúc

| File | Vai trò |
|---|---|
| `ecommerce_app.py` | Ứng dụng EduCommerce (Catalog, Cart, Promotions, Shipping, Inventory, Payments, Checkout) |
| `test_runner.py` | Runner: đọc CSV/XLSX, validate schema, fixture độc lập, dispatcher, so sánh expected/actual + state, PASS/FAIL/BLOCKED, xuất report |
| `test_cases.csv` | 38 test case data-driven (cột theo yêu cầu 1.5) |
| `sample_data/broken_cases.csv` | Bộ dữ liệu lỗi có chủ đích để chứng minh runner báo BLOCKED thay vì bỏ qua (bài 3.7) |
| `dashboard_gradio.py` | Dashboard Gradio: chart cạnh bảng, lọc theo REQ/status |
| `STLab02_EduCommerce.ipynb` | Notebook Colab chạy toàn bộ quy trình |
| `reports/` | Report mẫu: `test_execution.csv`, `test_report.xlsx` (Summary/ByRequirement/Traceability/Execution), `test_dashboard.html`, `test_summary_chart.png` |
| `docs/` | Report PDF, `test_design.xlsx` (REQ/COND/TS/TC), hình evidence, `isolation_check.py`, `reproduce_defects.py` |

## Chạy từ môi trường sạch (local)

```bash
git clone <URL-repo-của-bạn> && cd STLab02_EduCommerce
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python test_runner.py test_cases.csv --out reports
python test_runner.py sample_data/broken_cases.csv --out reports_selfcheck   # kiểm data completeness
python dashboard_gradio.py            # mở http://127.0.0.1:7860
```

## Chạy trên Google Colab

Mở `STLab02_EduCommerce.ipynb` trên Colab (File → Upload notebook hoặc Open from GitHub) và chạy lần lượt các cell. Cell đầu tiên `git clone` repository; sửa biến `REPO_URL` thành URL repo của bạn.

## Quy ước trạng thái

- **PASS**: mọi khóa trong `expected_json` khớp giá trị quan sát (return + state: orders, charges, stock_delta, used_codes, cart_lines…).
- **FAIL**: có khóa lệch (kể cả exception ngoài mong đợi từ ứng dụng).
- **BLOCKED**: không thực thi được do dữ liệu/setup (JSON lỗi, fixture/action không tồn tại). Dòng BLOCKED vẫn được tính vào tổng và pass rate.

Expected được suy ra từ acceptance criteria, **không** sửa theo actual.

## FAIL đã tìm thấy

| Defect | TC | Tóm tắt |
|---|---|---|
| DEF-001 | TC-PMT-002/003/004 | `Checkout.place()` gọi `inventory.reserve()` trước `payments.collect()`; method không hợp lệ ném lỗi nhưng **không release stock** → kho bị trừ dù không có order |
| DEF-002 | TC-CRT-005 | `Cart.add('A', True)` được chấp nhận vì `bool` là lớp con của `int` trong Python |
