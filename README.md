# 🚀 Facebook Automation Toolkit (`fbreg` & `fbspam`)

> **Bộ công cụ tự động hóa Facebook toàn diện:** Tự động tạo tài khoản Facebook (Account Factory), tự động vượt Captcha & Checkpoint, trích xuất cookie từ trình duyệt và gửi tin nhắn hàng loạt (Messenger Outreach/Fan-out) với đa luồng và xoay proxy.

---

## 📌 Tổng Quan Dự Án

Dự án này là giải pháp tự động hóa tương tác Facebook gồm 2 module độc lập nhưng có thể kết hợp chặt chẽ với nhau:

1. **`fbreg` (Facebook Account Creator)**: 
   - Tự động hóa toàn bộ quy trình đăng ký tài khoản Facebook mới dựa trên Playwright Chromium.
   - Vượt qua giao diện React hiện đại (không dùng `<form>` truyền thống).
   - Tự động lấy mã xác nhận OTP qua TempMail (`temp-mail.org` API) hoặc email tên miền riêng (Catch-all domain).
   - Tích hợp giải Arkose / FunCaptcha qua CapSolver, 2Captcha, AntiCaptcha hoặc giải thủ công (`manual`).
   - Tự động vượt qua màn hình xác minh/checkpoint ban đầu (`repair pass`).
   - Tích hợp xoay vòng Proxy (HTTP/SOCKS5) và kiểm tra proxy sống trước khi chạy.
   - Script chạy 1-click tiện lợi trên Windows qua file `TAO-ACC.cmd`.

2. **`fbspam` (Messenger Outreach / Fan-out Engine)**:
   - Tự động hóa gửi tin nhắn Facebook Messenger số lượng lớn bằng giao diện `mbasic` siêu nhẹ kết hợp fallback desktop.
   - Trích xuất cookie trực tiếp từ các trình duyệt trên máy (Chrome, Edge, Brave, Firefox, v.v.) bằng giải mã khóa Windows DPAPI / AES-GCM.
   - Hỗ trợ nhập danh sách cookie từ Playwright (`fbreg`), file JSONL hoặc text.
   - Hệ thống **Spintax** đa cấp `{xin chào|hello|hi}` chống trùng lặp nội dung.
   - Quản lý danh sách gửi linh hoạt: UID, username hoặc URL trang cá nhân.
   - Cơ chế lưu trạng thái (`State ledger`) chống gửi lặp lại người đã nhắn.
   - Chạy đa luồng (multi-threading), hỗ trợ Proxy riêng cho từng tài khoản và thời gian chờ ngẫu nhiên (random delay) chống checkpoint.

---

## 🗂 Cấu Trúc Thư Mục

```text
tool/
├── TAO-ACC.cmd              # Script Windows 1-click chạy tạo tài khoản
├── README.md                # Tài liệu hướng dẫn sử dụng dự án
├── .gitignore               # Loại bỏ file tạm và dữ liệu nhạy cảm
│
├── fbreg/                   # Module tạo tài khoản Facebook
│   ├── browser.py           # Điều khiển trình duyệt bằng Playwright
│   ├── captcha.py           # Bộ giải Arkose/FunCaptcha (API hoặc thủ công)
│   ├── client.py            # Client tương tác mạng/legacy form
│   ├── config.py            # Cấu hình danh tính, User-Agent, tham số
│   ├── identity.py          # Sinh thông tin họ tên, ngày sinh ngẫu nhiên
│   ├── proxy.py             # Quản lý, kiểm tra độ trễ và xoay proxy
│   ├── repair.py            # Tự động gỡ checkpoint sau khi đăng ký
│   ├── tempmail.py          # Tích hợp API temp-mail.org lấy OTP tự động
│   ├── verify.py            # Nhận diện và xử lý mã xác thực
│   ├── proxies.txt          # Danh sách proxy đầu vào
│   └── requirements.txt     # Thư viện cho fbreg
│
└── fbspam/                  # Module gửi tin nhắn hàng loạt
    ├── client.py            # Client tương tác mbasic/desktop messenger
    ├── cookies.py           # Trích xuất cookie từ trình duyệt & nạp tài khoản
    ├── sender.py            # Engine phân phối tin nhắn, đa luồng & Spintax
    ├── main.py              # CLI điều khiển fbspam
    ├── targets.txt          # Danh sách UID / Profile nhận tin
    ├── messages.txt         # Danh sách mẫu tin nhắn (hỗ trợ Spintax)
    └── requirements.txt     # Thư viện cho fbspam
```

---

## ⚙️ Cài Đặt Môi Trường

### 1. Yêu Cầu Hệ Thống
- Hệ điều hành: Windows 10/11 (khuyến nghị cho tính năng trích xuất cookie và chạy `TAO-ACC.cmd`).
- **Python 3.10+** (đã tích chọn "Add Python to PATH").

### 2. Cài Đặt Thư Viện

Mở Terminal / PowerShell tại thư mục gốc của dự án và chạy:

```bash
# Cài đặt thư viện cho fbreg & trình duyệt Chromium
pip install -r fbreg/requirements.txt
python -m playwright install chromium

# Cài đặt thư viện cho fbspam
pip install -r fbspam/requirements.txt
```

---

## 🚀 Hướng Dẫn Sử Dụng

### 1. Tạo Tài Khoản Nhanh (`TAO-ACC.cmd`)
Chỉ cần nhấp đúp vào file `TAO-ACC.cmd`. Bạn có thể chỉnh sửa nhanh các thông số ở đầu file:

```bat
set "COUNT=5"                 REM Số lượng tài khoản muốn tạo
set "WORKERS=1"               REM Số luồng chạy song song
set "USE_TEMPMAIL=1"          REM 1 = Dùng email tạm temp-mail.org tự động lấy mã
set "SOLVER=none"             REM none, capsolver, 2captcha, manual
set "SOLVER_KEY="             REM API key nếu dùng dịch vụ giải captcha
set "HEADED=1"                REM 1 = Hiện trình duyệt (cần thiết khi tự giải tay)
set "ALLOW_DIRECT=1"          REM 1 = Cho phép chạy bằng IP mạng hiện tại
```

Kết quả tài khoản sau khi tạo sẽ được lưu tại thư mục `out/run_YYYYMMDD_HHMMSS/`:
- `accounts.txt`: Định dạng `email | password | name | uid | proxy`.
- `accounts.jsonl`: Thông tin chi tiết kèm cookie.
- `cookies/<email>.json`: File session Playwright có thể tái sử dụng ngay.

---

### 2. Gửi Tin Nhắn Hàng Loạt (`fbspam`)

#### Bước 1: Chuẩn bị tài khoản
Bạn có thể trích xuất cookie trực tiếp từ trình duyệt của máy tính:
```bash
# Trích xuất phiên đăng nhập Facebook từ Chrome/Edge và xuất ra file
python -m fbspam dump --from-browsers --out cookies
```
Hoặc dùng trực tiếp danh sách tài khoản vừa tạo từ `fbreg`:
```bash
python -m fbspam check -a out/run_xxxx/accounts.jsonl
```

#### Bước 2: Chuẩn bị nội dung và danh sách nhận
- **`fbspam/targets.txt`**: Điền các UID, link Facebook hoặc Username của đối tượng mục tiêu.
- **`fbspam/messages.txt`**: Điền nội dung tin nhắn. Hỗ trợ **Spintax** để mỗi tin nhắn gửi đi mang nội dung khác nhau, ví dụ:
  ```text
  {Chào bạn|Hello bạn|Hi bạn}, {mình muốn trao đổi|mình gửi bạn thông tin} về dự án này nhé!
  ```

#### Bước 3: Chạy gửi tin nhắn
```bash
python -m fbspam run -a out/run_xxxx/accounts.jsonl -t fbspam/targets.txt -m fbspam/messages.txt --workers 2 --delay-min 15 --delay-max 30
```

---

## ⚠️ Tuyên Bố Miễn Trừ Trách Nhiệm (Disclaimer)

Dự án này được phát triển chỉ nhằm mục đích **nghiên cứu bảo mật, học tập và kiểm thử tự động hóa (Automation Testing)**. Tác giả không chịu trách nhiệm cho bất kỳ hành vi sử dụng trái phép, lạm dụng hoặc vi phạm Điều khoản Dịch vụ (Terms of Service) của nền tảng Facebook / Meta. Vui lòng tuân thủ đúng quy định pháp luật và chính sách dịch vụ.
