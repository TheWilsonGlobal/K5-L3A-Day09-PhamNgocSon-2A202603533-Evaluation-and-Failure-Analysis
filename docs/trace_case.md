# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case đã điền: C-002 @ seed 11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run `E-seeded_regression-20261117-da6c` (`reports/eval_seeded_regression.json`) |
| Triệu chứng | lab8 FAIL (`status resolved != denied`). `RefundAmountCorrect` = 0 (sổ cái 20.000đ, nhãn 0). `DbFactKept` = 0. Reply "đã hoàn 20.000đ" khớp sổ cái, nên `ReplyLedgerMatch` không bắt được. |
| Bước sai đầu tiên | **Event 3**, `model_override`, `{"delay_days": 5}`. Đơn O-202 có `delay_days = 2` trong bảng `orders`. |
| Vì sao là bước *đầu tiên* | Event 1 (`handoff`) đúng: cùng `claim_id`, phạm vi `owner_order_only`. Event 2 (`investigator`) đúng: `lookup_order` trả `delay_days` 2 từ DB. Event 3 là lần đầu dữ liệu ticket (5 ngày, do khách khai) thay thế dữ liệu DB. Các bước sau (`quote` 20.000đ, `reply`) là hệ quả. |
| Failure mode | **FM-03** `ticket_trust`. Hệ quả kéo theo: FM-04 (đề xuất 20.000đ thay vì 0) và sổ cái sai. |
| Đối chứng | `fixed C-002@11`: không có `model_override`; `quote` `amount_vnd 0`, `reason no_entitlement`; reply "chưa đủ điều kiện"; sổ cái 0; lab8 PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_seeded_regression_overrides_db_at_event_3` (event 3 là `model_override`, sổ cái 20.000đ), `test_the_code_grader_catches_it` (`DbFactKept` và `RefundAmountCorrect` đều FAIL), `test_fixed_keeps_the_db_fact` (fixed không override). Cả 3 PASS, đã kiểm tra trên variant lỗi và `fixed`. |
| Chưa chắc chắn | Trace chỉ cho thấy việc chọn ticket xảy ra ở event 3, không chứng minh *vì sao* agent chọn như vậy. Với `ticket_trust` (bật vô điều kiện), bước này không phụ thuộc seed. Trên `swarm` thật, lỗi chỉ xuất hiện ở seed 55 (seed % 5 == 0), và một seed đơn lẻ không đủ để thống kê. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai. Trong case này reply và sổ cái sai giống nhau nên `ReplyLedgerMatch` không đủ, phải dựa vào `DbFactKept` ở event 3.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: `src/tests/test_lab9_trace_case.py`.
