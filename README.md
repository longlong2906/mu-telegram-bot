# Manchester United Telegram Bot

Bot gửi lịch và kết quả của đội một nam Manchester United vào **một chat cá nhân**.
Dữ liệu lấy miễn phí từ ESPN, bao gồm mọi giải chính thức nguồn cung cấp, loại trận giao hữu.
Python 3.13, thư viện quản lý bằng uv; GitHub Actions kiểm tra mỗi 5 phút, không cần thuê server.

## Bot gửi những gì?

- Nhắc trước 24 giờ và 1 giờ, gồm hai đội, giải, sân nếu có và giờ Việt Nam (UTC+7).
- Nếu lượt kiểm tra chạy trễ, gửi mốc còn phù hợp; khi còn dưới một giờ chỉ gửi mốc một giờ.
- Cập nhật giờ bóng lăn nếu lịch đổi sau khi đã nhắc. Mốc nhắc được tính lại theo giờ mới.
- Báo kết quả sau khi ESPN xác nhận đã kết thúc, gồm hiệp phụ hoặc luân lưu khi có dữ liệu.
- Không nhắc trận đang thi đấu, giờ chưa xác nhận, trận hoãn hoặc hủy.

Đây là bot gửi thông báo theo lịch, không có tiến trình chạy liên tục hay webhook.
Lệnh `/start` dùng để mở chat ban đầu; bot không xử lý lệnh hỏi lịch trực tiếp.

## 1. Tạo bot Telegram

1. Mở [BotFather](https://t.me/BotFather), gửi `/newbot`, chọn tên và username.
2. Lưu token BotFather cấp. Không đưa token vào mã nguồn, commit hoặc URL chia sẻ.
3. Mở chat với bot vừa tạo, nhấn **Start** hoặc gửi `/start`.

## 2. Cài và thử trên máy

Cài [uv](https://docs.astral.sh/uv/getting-started/installation/), mở terminal trong thư mục dự án:

```powershell
uv sync --locked
uv run mu-bot check --dry-run
```

uv sẽ cài Python 3.13 nếu máy chưa có. Dry-run không cần Telegram token, không gửi tin và
không tạo hoặc sửa trạng thái. Khi chưa đến mốc nhắc, vẫn hiển thị ba trận sắp tới để kiểm tra dữ liệu.

Lấy chat ID trên máy local (không chạy lệnh này trong log công khai của Actions):

```powershell
$env:TELEGRAM_BOT_TOKEN = 'TOKEN_CUA_BAN'
uv run mu-bot chat-id
```

Sao chép số dương ở dòng `TELEGRAM_CHAT_ID=...`. Nếu có nhiều ID, chọn chat của bạn;
có thể gửi lại `/start` để tạo cập nhật mới. Telegram chỉ giữ cập nhật chưa nhận tối đa 24 giờ.

Muốn chạy thật trên máy, tạo `.env` từ `.env.example`, điền token và ID, rồi chạy:

```powershell
uv run --env-file .env mu-bot check
```

File `.env`, `.state/` và môi trường `.venv/` đã được gitignore. Trạng thái local và trạng thái
GitHub là hai lịch sử riêng; tránh chạy gửi thật ở cả hai nơi để không nhận thông báo trùng.

## 3. Đưa lên GitHub và bật lịch

1. Tạo một repository **public** trên GitHub, đưa toàn bộ mã nguồn lên nhánh mặc định
   (thường là `main`), bao gồm `uv.lock` và `.github/workflows/`.
2. Vào **Settings → Secrets and variables → Actions → New repository secret**, thêm:

   | Secret | Giá trị |
   | --- | --- |
   | `TELEGRAM_BOT_TOKEN` | Token BotFather cấp |
   | `TELEGRAM_CHAT_ID` | ID số dương của chat cá nhân |

3. Mở **Actions**, cho phép chạy workflow nếu GitHub yêu cầu. Workflow khai báo quyền
   `contents: write`; chính sách repository/organization phải cho phép quyền này.
4. Chọn **Manchester United notifications → Run workflow**, chọn nhánh mặc định và giữ
   `dry_run` bật để kiểm tra dữ liệu. Sau đó tắt `dry_run` và chạy lại để khởi tạo trạng thái thật.
5. Lịch `2-59/5 * * * *` chạy ở phút 02, 07, 12, …, 57 mỗi giờ UTC.

`GITHUB_TOKEN` do Actions tự cấp, không cần tạo personal access token. Nhánh `bot-state`
được tự tạo từ nhánh mặc định và lưu `state.json`; không chứa token hay chat ID. Không xóa
nhánh/file này, vì đó là lịch sử chống gửi lại. Không đặt quy tắc chặn bot ghi vào nhánh này.
Workflow chỉ chạy thông báo từ nhánh mặc định; CI không chạy khi nhánh `bot-state` cập nhật.

Lần đầu bot bỏ qua kết quả đã kết thúc, vẫn theo dõi trận đang diễn ra và nhắc các trận
sắp tới nếu đến hạn. Vì vậy lượt khởi tạo có thể không gửi tin nào. Nếu muốn kiểm tra đường
gửi Telegram ngay, chạy từ terminal local với hai biến môi trường đã điền:

```powershell
uv run python -c "import os,httpx; from mu_bot.telegram import Telegram; c=httpx.Client(timeout=20); Telegram(c,os.environ['TELEGRAM_BOT_TOKEN'],os.environ['TELEGRAM_CHAT_ID']).send('Kết nối bot Manchester United thành công!'); c.close()"
```

Nếu dùng `.env`, thêm `--env-file .env` ngay sau `uv run`. Lệnh trên gửi đúng một tin thử,
không sửa lịch sử thông báo. Không dán token trực tiếp vào lệnh.

## Trạng thái và lỗi

Bot đọc trạng thái, lấy lịch/kết quả, kiểm tra lưu được trạng thái rồi mới gửi. Sau từng tin
thành công, trạng thái được lưu ngay; lưu thất bại thì dừng lượt chạy. Các lỗi làm workflow
thất bại để bạn thấy trong Actions, không ghi token, chat ID hay nội dung phản hồi lỗi vào log.

Các truy vấn dữ liệu thử lại tối đa ba lần. Telegram rate limit được chờ tối đa 30 giây mỗi
lần; timeout lúc gửi không được gửi lại tức thì vì Telegram có thể đã nhận tin. Nếu tiến trình
dừng sau khi gửi nhưng trước khi lưu, lượt sau vẫn có thể gửi trùng: không bảo đảm đúng một lần
tuyệt đối giữa hai dịch vụ độc lập.

Sau gián đoạn, kết quả chưa gửi được gửi bù cho trận bắt đầu trong bảy ngày gần nhất.
Trận đã theo dõi nhưng biến mất khỏi lịch mùa hiện tại được tra lại qua endpoint chi tiết.
Mỗi ngày UTC thành công cập nhật một mốc trong trạng thái kể cả nghỉ mùa; lịch sử không
dùng Actions cache hoặc artifact có thể hết hạn.

Nếu trạng thái lỗi, khôi phục `state.json` từ commit tốt gần nhất của nhánh `bot-state` rồi
chạy dry-run. Không tự xóa lịch sử để chữa lỗi vì có thể gửi lại thông báo cũ.

## Chi phí và giới hạn

Runner GitHub-hosted tiêu chuẩn trên repo public được miễn phí theo
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
Workflow dùng Ubuntu, cache nhỏ của uv, không tải lên artifact. Repo private bị hạn mức phút
theo gói tài khoản và chạy mỗi 5 phút có thể vượt hạn mức miễn phí.

Theo [tài liệu schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
Actions có thể chạy trễ hoặc bỏ lượt; repo public không có hoạt động 60 ngày có thể bị tắt
lịch. Nếu bị tắt, vào **Actions → Manchester United notifications → Enable workflow**.
Chu kỳ 5 phút không bảo đảm nhận kết quả trong đúng 5 phút.

ESPN là endpoint của website, không có cam kết API ổn định cho dự án này. Độ đầy đủ và tốc độ
cập nhật phụ thuộc nguồn. Nếu cấu trúc thay đổi, bộ đọc sẽ báo lỗi thay vì suy đoán tỷ số;
sửa bộ đọc và chạy lại kiểm thử. Secrets vẫn cần được cấu hình dù mã nguồn public.

## Kiểm thử và cấu hình

```powershell
uv run ruff check .
uv run pytest
```

Kiểm thử dùng dữ liệu mẫu và HTTP mock, không gửi Telegram thật hoặc ghi GitHub thật.

| Biến môi trường | Mặc định / ý nghĩa |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bắt buộc khi gửi hoặc lấy chat ID |
| `TELEGRAM_CHAT_ID` | Bắt buộc khi gửi, một chat cá nhân |
| `STATE_BACKEND` | `local` trên máy, `github` trong workflow |
| `STATE_FILE` | `.state/state.json` với backend local |
| `GITHUB_REPOSITORY` | Actions tự cấp dạng `owner/repo` |
| `GITHUB_TOKEN` | Actions tự cấp; workflow truyền cho bot |
