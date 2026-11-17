# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`. Nhãn người (`human`) so với judge replay (`judge`), FAIL là lớp dương tính.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok (`judge_tone_public.csv`) | 100 | 0.757 | 0.857 | 0.800 | Có (κ 0.757 ≥ 0.60, P 0.857 ≥ 0.80, R 0.80 ≥ 0.70) | **dùng làm gate** |
| helpful (`judge_helpful_public.csv`) | 100 | 0.375 | 1.000 | 0.300 | Không (κ < 0.60, R < 0.70) | **loại (REJECT)** |

Ma trận nhầm lẫn (FAIL là dương tính):

- tone: TP 24, FP 4, FN 6, TN 66. Tỉ lệ FAIL quan sát 0.28, hiệu chỉnh Rogan-Gladen 0.30.
- helpful: TP 9, FP 0, FN 21, TN 70. Tỉ lệ FAIL quan sát 0.09, hiệu chỉnh 0.30.

## ≥5 case audit thủ công (tone, mâu thuẫn Human ↔ Judge)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" với khách, thêm "nha": suồng sã. Judge coi là thân thiện. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha." | PASS | FAIL | Người | Gọi "bạn" với khách lớn tuổi. Judge bỏ qua xưng hô. |
| 3 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Giọng ra lệnh. Judge chỉ thấy "Dạ, vui lòng". |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ngắn nhưng đủ ý, lịch sự. Judge phạt vì "thiếu xin lỗi". Rubric không yêu cầu xin lỗi mọi câu. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | Dùng "refund" là từ CS LogiX cho phép. Judge phạt vì tiếng Anh. |

Bốn trong năm ca là lỗi rubric của judge (xưng hô, mệnh lệnh, từ tiếng Anh, xin lỗi), không phải lỗi ngẫu nhiên. Mặc dù vậy, tone vẫn đạt floors, nên giữ làm gate, với **đề xuất sửa rubric**:
1. Xưng hô: cấm "em" và "bạn" khi không rõ khách; mặc định "anh/chị".
2. Không ra lệnh cho khách ("không cần nhắn thêm").
3. Từ tiếng Anh đã được LogiX chấp nhận (refund) không bị phạt.
4. Xin lỗi chỉ bắt buộc khi có sự cố; không phạt câu trả lời ngắn đúng.

## Helpful bị loại: vì sao

Judge helpful chỉ bắt được 9 trên 30 câu bị người đánh FAIL (R = 0.30). Mọi câu nó đánh FAIL đều đúng (P = 1.0, không có FP), nhưng nó bỏ sót 21 câu trả lời sai. Phần lớn câu bị người đánh FAIL là **sai tiền** (ví dụ HL-015: reply "hoàn 55.000đ" trong khi sổ cái 40.000đ; HL-020: "hoàn 90.000đ", sổ cái 120.000đ). Judge đọc trôi chảy nên cho PASS. Đây đúng là lý do tiền phải chấm bằng code: `ReplyLedgerMatch` so số tiền reply với sổ cái và bắt được các ca này. Judge không được dùng làm gate cho tiêu chí "hữu ích".

## Kết luận

- **tone_ok**: đạt floors (κ 0.757, P 0.857, R 0.80). Dùng làm gate mềm, với rubric đã sửa theo bảng trên trước khi đưa vào CI có khóa.
- **helpful**: không đạt floors (κ 0.375, R 0.30). Loại. Các lỗi "hữu ích" nghiêm trọng đã được code grader chặn (`ReplyLedgerMatch`, `RefundAmountCorrect`).
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai, 100 mẫu mỗi bộ; cần nhãn người mới (held-out) để có kết luận thật. Số liệu judge là của replay, không phải của một model thật.
