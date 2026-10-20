# Contributing to Facebook Automation Toolkit

Cảm ơn bạn đã quan tâm đến việc đóng góp cho dự án! Mọi đóng góp nhằm cải thiện hiệu năng, tính năng và độ ổn định của toolkit đều được hoan nghênh.

## Quy trình đóng góp (Workflow)

1. **Fork** dự án về tài khoản GitHub của bạn.
2. Tạo một nhánh mới (branch) cho tính năng hoặc sửa lỗi của bạn:
   ```bash
   git checkout -b feature/ten-tinh-nang
   # hoặc
   git checkout -b fix/loi-can-sua
   ```
3. Thực hiện thay đổi và kiểm tra cẩn thận mã nguồn.
4. Commit thay đổi với thông điệp rõ ràng:
   ```bash
   git commit -m "feat: thêm tính năng hỗ trợ proxy SOCKS5 có user/pass"
   ```
5. Đẩy nhánh lên fork của bạn:
   ```bash
   git push origin feature/ten-tinh-nang
   ```
6. Mở một **Pull Request (PR)** trên nhánh `main` của repo gốc kèm theo mô tả chi tiết về thay đổi.

## Báo cáo lỗi (Issue)

Nếu bạn gặp sự cố hoặc có ý tưởng mới:
- Vui lòng kiểm tra các Issues đã mở trước khi tạo mới để tránh trùng lặp.
- Cung cấp nhật ký lỗi (`attempts.log`), môi trường chạy (HĐH, phiên bản Python) và các bước tái hiện lỗi cụ thể.
