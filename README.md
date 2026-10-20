<p align="center">
  <img src="assets/logo.svg" alt="Facebook Automation Toolkit Logo" width="100%">
</p>

<p align="center">
  <a href="https://github.com/kiyogo/glowing-octo-train/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License MIT">
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python Version">
  </a>
  <a href="https://playwright.dev/">
    <img src="https://img.shields.io/badge/Playwright-Chromium-45ba4b?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright">
  </a>
  <a href="https://github.com/kiyogo/glowing-octo-train">
    <img src="https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Platform Windows">
  </a>
  <a href="https://github.com/kiyogo/glowing-octo-train/pulls">
    <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen.svg?style=for-the-badge" alt="PRs Welcome">
  </a>
</p>

---

## 📖 Giới Thiệu (Overview)

**Facebook Automation Toolkit** là bộ giải pháp mã nguồn mở mạnh mẽ và tự động hóa toàn diện dành cho Facebook, bao gồm 2 module chuyên sâu:

1. **`fbreg` (Account Factory Engine):** Tự động hóa đăng ký tài khoản Facebook với Playwright Chromium, tự động vượt rào giao diện React không form, tích hợp API lấy OTP từ Temp-Mail, giải Arkose/FunCaptcha tự động và cơ chế tự sửa/gỡ checkpoint sau tạo (`repair pass`).
2. **`fbspam` (Messenger Outreach & Fan-out Engine):** Hệ thống gửi tin nhắn hàng loạt đa luồng qua giao diện `mbasic` siêu nhẹ kết hợp fallback desktop, tự động giải mã và trích xuất cookie từ các trình duyệt Chromium trên Windows (DPAPI + AES-GCM), hỗ trợ **Spintax** ngẫu nhiên hóa nội dung và chống checkpoint.

---

## 🌟 Tính Năng Nổi Bật (Key Features)

### 🔹 Module `fbreg` — Tạo Tài Khoản Tự Động
- 🎭 **Tự động hóa Playwright Chromium:** Mô phỏng thao tác người dùng thật (gõ phím ngẫu nhiên, chuột, delay tự nhiên), vượt qua giao diện React hiện đại.
- ✉️ **Tự động nhận OTP qua Temp-Mail:** Tích hợp API `temp-mail.org` sinh hòm thư ngẫu nhiên và tự động đọc mã xác thực OTP hoặc link kích hoạt để xác minh.
- 🧩 **Tích hợp Giải Captcha Đa Năng:** Hỗ trợ API CapSolver, 2Captcha, Anti-Captcha hoặc chế độ thủ công (`manual`) hiển thị trình duyệt để người dùng tự xác thực.
- 🛠️ **Cơ chế Repair Pass:** Tự động phát hiện và vượt qua màn hình xác nhận danh tính mới tạo (`/checkpoint/` và `confirmemail.php`).
- 🌐 **Xoay Vòng Proxy Thông Minh:** Hỗ trợ proxy pool (HTTP/SOCKS5), tự động kiểm tra IP sống/chết và độ trễ trước khi đăng ký.
- 🖱️ **1-Click Windows Script:** Chạy tự động chỉ với 1 cú nhấp đúp qua file `TAO-ACC.cmd`.

### 🔹 Module `fbspam` — Tiếp Cận Messenger Hàng Loạt
- 🍪 **Trích Xuất Cookie Trực Tiếp:** Giải mã phiên đăng nhập Facebook từ Chrome, Edge, Brave, Opera, Firefox trên Windows mà không cần đăng nhập lại.
- ⚡ **Kiến Trúc mbasic Siêu Nhẹ:** Tối ưu hóa gửi tin nhắn qua giao diện mobile basic, tiêu tốn cực ít băng thông và hạn chế checkpoint tối đa.
- 🔀 **Bộ Xử Lý Spintax Đa Tầng:** Hỗ trợ định dạng `{Chào|Hello|Hi} bạn, {mình gửi|bên mình có}...` giúp mỗi tin nhắn gửi đi là độc nhất.
- 🧵 **Đa Luồng (Multi-Threading):** Gửi song song nhiều tài khoản với thời gian chờ (delay) ngẫu nhiên.
- 📋 **Resume Ledger (Chống Trùng Lặp):** Lưu trữ trạng thái gửi theo thời gian thực, đảm bảo không bao giờ nhắn 2 lần cho cùng một người nhận.

---

## 🏗️ Sơ Đồ Quy Trình Hoạt Động (Architecture Flow)

```text
               +--------------------------------------------------+
               |                  TAO-ACC.cmd                     |
               |       (Kiểm tra Python, Chromium & Proxy)        |
               +------------------------+-------------------------+
                                        |
                 [1] KHỞI TẠO TÀI KHOẢN | (fbreg)
                                        v
     +---------------------------------------------------------------+
     |  Playwright Browser  <--->  Proxy Pool (HTTP/SOCKS5)          |
     |         |                                                     |
     |         +---> Sinh danh tính ngẫu nhiên (Họ tên, ngày sinh)   |
     |         +---> Nhận Mail từ Temp-Mail API                      |
     |         +---> Điền Form React & Submit                        |
     |         +---> Vượt Arkose FunCaptcha (Solver API / Manual)    |
     |         +---> Đọc mã OTP từ hòm thư ảo & Xác nhận             |
     |         +---> Repair Pass: Xử lý checkpoint mới               |
     +---------------------------------+-----------------------------+
                                       |
                                       | Xuất cookie session (out/)
                                       v
                 [2] GỬI TIN NHẮN HÀNG LOẠT | (fbspam)
                                       v
     +---------------------------------------------------------------+
     |  Nạp Cookie (Từ fbreg HOẶC trích xuất từ Chrome/Edge DPAPI)   |
     |         |                                                     |
     |         +---> Kiểm tra Live/Dead qua Ping                      |
     |         +---> Phân tách Targets (UID, Username, Profile Link) |
     |         +---> Biến thể nội dung với Spintax {A|B|C}           |
     |         +---> Gửi qua mbasic / desktop messenger               |
     |         +---> Ghi sổ State Ledger (Tránh trùng lặp)           |
     +---------------------------------------------------------------+
```

---

## 📁 Cấu Trúc Thư Mục (Project Structure)

```text
.
├── .gitignore               # Bộ lọc file tạm, cache, cookie và dữ liệu nhạy cảm
├── LICENSE                  # Giấy phép phần mềm mã nguồn mở MIT
├── README.md                # Tài liệu hướng dẫn sử dụng chính
├── CONTRIBUTING.md          # Hướng dẫn đóng góp mã nguồn
├── SECURITY.md              # Chính sách báo cáo bảo mật
├── TAO-ACC.cmd              # Script Windows 1-click chạy tạo tài khoản
├── assets/
│   └── logo.svg             # Logo đồ họa vector chính thức của dự án
│
├── fbreg/                   # Module tự động tạo tài khoản Facebook
│   ├── browser.py           # Engine điều khiển Playwright Chromium
│   ├── captcha.py           # Module nhận diện và giải Arkose FunCaptcha
│   ├── client.py            # HTTP Client cho luồng HTML fallback
│   ├── config.py            # Cấu hình danh tính, User-Agent, timeouts
│   ├── form.py              # Xử lý các thẻ chọn ngày sinh, giới tính
│   ├── identity.py          # Bộ sinh tên tuổi và mật khẩu ngẫu nhiên
│   ├── main.py              # CLI chính của fbreg
│   ├── proxy.py             # Bộ quản lý kiểm tra và phân phối proxy
│   ├── proxies.txt          # Danh sách proxy đầu vào (IP:Port:User:Pass)
│   ├── register.py          # Điều phối luồng đăng ký tài khoản
│   ├── repair.py            # Tự động gỡ checkpoint sau khi tạo
│   ├── requirements.txt     # Danh sách thư viện phụ thuộc của fbreg
│   ├── tempmail.py          # Tích hợp API temp-mail.org
│   └── verify.py            # Xử lý tự động nhập OTP
│
└── fbspam/                  # Module tự động hóa nhắn tin Messenger
    ├── client.py            # Client xử lý gửi tin qua mbasic & desktop
    ├── cookies.py           # Trích xuất và giải mã cookie từ trình duyệt Windows
    ├── main.py              # CLI chính của fbspam
    ├── messages.txt         # Mẫu tin nhắn (hỗ trợ Spintax)
    ├── requirements.txt     # Danh sách thư viện phụ thuộc của fbspam
    ├── sender.py            # Động cơ phân phối tin nhắn, đa luồng & state ledger
    └── targets.txt          # Danh sách mục tiêu (UID / link Facebook)
```

---

## ⚡ Cài Đặt Nhanh (Installation)

### 1. Yêu Cầu Tiên Quyết
- Hệ điều hành: **Windows 10 / 11** (để hỗ trợ đầy đủ `TAO-ACC.cmd` và trích xuất cookie DPAPI).
- **Python 3.10 trở lên** (chú ý tích chọn *"Add Python to PATH"* khi cài đặt).

### 2. Cài Đặt Thư Viện

Mở PowerShell tại thư mục dự án và chạy:

```powershell
# Cài đặt thư viện tạo tài khoản & Playwright Chromium
pip install -r fbreg/requirements.txt
python -m playwright install chromium

# Cài đặt thư viện gửi tin nhắn & trích xuất cookie
pip install -r fbspam/requirements.txt
```

---

## 🚀 Hướng Dẫn Sử Dụng (Quick Start)

### 1. Tạo Tài Khoản Facebook Tự Động (`TAO-ACC.cmd`)

Chỉ cần mở file `TAO-ACC.cmd` bằng Notepad để chỉnh sửa thông số theo ý muốn, sau đó **nhấp đúp** để chạy:

```bat
set "COUNT=5"                 REM Số lượng tài khoản muốn tạo
set "WORKERS=1"               REM Số luồng chạy đồng thời
set "USE_TEMPMAIL=1"          REM 1 = Dùng hòm thư temp-mail.org tự động lấy mã
set "EMAIL_DOMAIN=mydomain"   REM Tên miền riêng nếu USE_TEMPMAIL=0
set "SOLVER=none"             REM none, capsolver, 2captcha, manual
set "SOLVER_KEY="             REM API key giải captcha (nếu có)
set "HEADED=1"                REM 1 = Mở cửa sổ trình duyệt (cần thiết khi giải tay)
set "ALLOW_DIRECT=1"          REM 1 = Cho phép chạy không cần proxy
set "DELAY=20,55"             REM Thời gian chờ ngẫu nhiên giữa các lần tạo (giây)
set "REPAIR=1"                REM 1 = Tự động gỡ checkpoint sau khi tạo
set "DRYRUN=0"                REM 1 = Chạy thử điền form nhưng không bấm gửi
```

Kết quả sẽ được tự động xuất ra thư mục `out/run_YYYYMMDD_HHMMSS/`:
- `accounts.txt`: Danh sách tài khoản dạng bảng: `email  password  name  uid  proxy`.
- `accounts.jsonl`: Dữ liệu chi tiết dạng JSON kèm toàn bộ cookie.
- `cookies/<email>.json`: Phiên lưu trữ sẵn sàng dùng lại với Playwright hoặc nạp vào `fbspam`.

---

### 2. Gửi Tin Nhắn Hàng Loạt (`fbspam`)

#### Bước 1: Thu thập phiên đăng nhập / Cookie
Bạn có thể trích xuất trực tiếp cookie của các tài khoản Facebook đang đăng nhập trên trình duyệt:
```powershell
# Trích xuất phiên Facebook từ các trình duyệt trên máy
python -m fbspam dump --from-browsers --out cookies
```
Hoặc kiểm tra độ sống của danh sách tài khoản vừa tạo từ `fbreg`:
```powershell
python -m fbspam check -a out/run_xxxx/accounts.jsonl
```

#### Bước 2: Chuẩn bị nội dung tin nhắn và mục tiêu
- Chỉnh sửa file `fbspam/targets.txt`: Thêm danh sách UID, Username hoặc Link profile (mỗi dòng 1 người).
- Chỉnh sửa file `fbspam/messages.txt`: Thêm nội dung tin nhắn với cú pháp **Spintax**, ví dụ:
  ```text
  {Chào bạn|Hello|Hi bạn}, {mình thấy bài viết của bạn rất hay|mình kết nối với bạn nhé}!
  ```

#### Bước 3: Chạy gửi tin nhắn
```powershell
python -m fbspam run -a out/run_xxxx/accounts.jsonl -t fbspam/targets.txt -m fbspam/messages.txt --workers 2 --delay-min 15 --delay-max 35
```

---

## ⚙️ Bảng Tham Số Dòng Lệnh (CLI Options)

### `fbreg` Options
| Tham số | Ý nghĩa | Ví dụ |
| :--- | :--- | :--- |
| `-n, --count` | Số lượng tài khoản muốn tạo | `-n 10` |
| `-w, --workers` | Số luồng chạy song song | `-w 2` |
| `--tempmail` | Sử dụng hòm thư ảo temp-mail.org | `--tempmail` |
| `-d, --domain` | Sử dụng catch-all email domain riêng | `-d mail.mydomain.com` |
| `--solver` | Nhà cung cấp giải captcha (`capsolver`, `2captcha`, `manual`) | `--solver capsolver` |
| `--solver-key` | API key tương ứng của dịch vụ giải captcha | `--solver-key YOUR_KEY` |
| `--headed` | Mở giao diện trình duyệt trực quan | `--headed` |
| `-p, --proxy-file` | Đường dẫn file danh sách proxy | `-p fbreg/proxies.txt` |
| `--check-proxies` | Kiểm tra IP và độ trễ toàn bộ proxy trước khi chạy | `--check-proxies` |
| `--dry-run` | Điền thông tin thử nghiệm và chụp ảnh, không submit | `--dry-run` |

---

## 🤝 Đóng Góp (Contributing)

Mọi đóng góp từ cộng đồng đều được hoan nghênh! Hãy xem file [CONTRIBUTING.md](CONTRIBUTING.md) để biết chi tiết về quy trình tạo nhánh, gửi Pull Request và báo cáo sự cố.

---

## 📄 Giấy Phép (License)

Dự án được phân phối dưới giấy phép mã nguồn mở **MIT License**. Xem file [LICENSE](LICENSE) để biết thêm thông tin.

---

## ⚠️ Tuyên Bố Miễn Trừ Trách Nhiệm (Disclaimer)

> [!WARNING]
> Phần mềm này được phát triển **hoàn toàn nhằm mục đích học tập, nghiên cứu kỹ thuật bảo mật và thử nghiệm tự động hóa (Automation Testing)**.
> Tác giả không chịu bất kỳ trách nhiệm pháp lý nào đối với việc sử dụng công cụ này vào mục đích lạm dụng, quấy rối, gửi thư rác trái phép hoặc bất kỳ hành vi nào vi phạm **Điều khoản dịch vụ của Meta / Facebook**. Người sử dụng hoàn toàn chịu trách nhiệm về hành động của mình.
