# ViTrans — dịch game indie sang tiếng Việt

Giao diện PyQt6 + dòng lệnh. Trích chữ từ game → dịch bằng AI **có ngữ cảnh, từ điển, xưng hô** → bạn duyệt/sửa → ghi
vào game (có sao lưu, khôi phục được) hoặc xuất riêng **bản vá** để chia sẻ.

| Loại game | Cách làm | Ghi chú |
|---|---|---|
| RPG Maker MV/MZ | Sửa JSON trong `data/` | Gộp dòng, ngắt lại theo độ rộng hộp thoại, tách trang ≤ 4 dòng, đổi font |
| Ren'Py (có `.rpy`) | Sinh `game/tl/vietnamese/` + ép ngôn ngữ | Game chỉ có `.rpyc` thì chưa đọc được |
| JSON chung | Quét chuỗi giống câu văn | Dự phòng, cần duyệt kỹ |

## Cài đặt (Arch)
```bash
sudo pacman -S python-pyqt6 python-requests python-fonttools
unzip vitrans_project.zip && cd vitrans_project
python -m vitrans            # mở giao diện
```

## Cách dùng
1. **Mở game** → chọn thư mục game (có `www/data` hoặc `game/`). Nhận sai loại thì đổi ở ô engine trên thanh công cụ.
2. **Cài đặt** → chọn nhà cung cấp dịch:
   - **Claude (Anthropic)**: dán khóa API (hoặc `export ANTHROPIC_API_KEY=...`). Chất lượng tốt nhất, tốn phí.
   - **OpenAI-tương thích / Ollama**: địa chỉ + model + khóa của dịch vụ bạn chọn. Ollama chạy máy mình thì miễn phí
     nhưng cần máy đủ mạnh.
   - **Google Dịch**: miễn phí, chất lượng thấp, không có ngữ cảnh/từ điển. Chỉ để thử.
   - **Chế độ thử**: không dịch thật, chỉ thêm `(VI)` để kiểm tra quy trình mà không tốn tiền. **Nên chạy chế độ này đầu tiên.**
3. Tab **Từ điển** → "Gợi ý từ tên nhân vật"; tab **Phong cách** → thể loại, giọng văn, cách xưng hô.
4. **Dịch phần chờ** (app sẽ nói trước số câu/ký tự sẽ gửi đi và hỏi xác nhận nếu dùng dịch vụ bên ngoài).
   Lọc "Có cảnh báo"/"Lỗi", sửa ở khung bên phải (Ctrl+Enter = lưu & duyệt).
5. **Áp dụng vào game** hoặc **Xuất bản vá**. **Khôi phục gốc** trả game về tiếng Anh.

CLI: `python -m vitrans scan|translate|stats|apply|export|restore GAME`

## Ren'Py: cách hoạt động (đã đối chiếu với mã nguồn Ren'Py)
Công cụ ghi `game/tl/vietnamese/vitrans_strings.rpy` (khối `translate vietnamese strings`) và `game/vitrans_language.rpy`
(`config.language = "vietnamese"`). Điểm mấu chốt đã kiểm chứng trong mã nguồn Ren'Py:
- Lời thoại **có** đi qua bảng dịch chuỗi (`Character.prefix_suffix` → `substitute(translate=True)`).
- `config.default_language` **chỉ có tác dụng ở lần chạy đầu** của game, nên mặc định công cụ dùng `config.language`
  (áp dụng mọi lần khởi động). Có thể đổi trong Cài đặt.
- Hai câu chỉ khác nhau về khoảng trắng là **cùng một khóa**; trùng khóa làm Ren'Py không khởi động, nên công cụ khử trùng
  theo giá trị Ren'Py chuẩn hóa.

**Nếu game vẫn hiện tiếng Anh:** chạy thử `RENPY_LANGUAGE=vietnamese ./TenGame.sh`. Biến môi trường này ép ngôn ngữ ở mức
cao nhất; nếu lúc đó hiện tiếng Việt thì lỗi ở khâu đặt ngôn ngữ, còn nếu vẫn tiếng Anh thì chuỗi không khớp — hãy báo lại.

## An toàn & bảo mật
Thư mục game và đầu ra của AI đều được coi là **không đáng tin**.
- **Đường dẫn:** mọi đọc/ghi qua `safe_join` (chặn `..`, đường dẫn tuyệt đối, NUL); không đi theo liên kết tượng trưng; kiểm
  tra toàn bộ đường dẫn trước khi ghi bất cứ thứ gì; giới hạn kích thước/độ sâu JSON/số tệp; regex có giới hạn (chống ReDoS).
- **Sao lưu:** ghi nguyên tử, giữ quyền tệp; bản gốc trong `.vitrans_backup`; manifest có mã băm và được lọc vì nằm trong
  thư mục game. Game tự cập nhật sau khi vá thì bản cập nhật **không bị ghi đè** khi khôi phục.
- **Đầu ra AI:** mã điều khiển/biến phải giữ nguyên **và không được thêm mã mới** (`{b}`, `[x.__class__]`, `\V[9]`...);
  dấu `{`/`[` lẻ bị chặn (Ren'Py sẽ báo lỗi); chuẩn hóa NFC, loại ký tự vô hình/điều khiển chiều chữ; giới hạn độ dài;
  chuỗi Ren'Py luôn được escape hợp lệ. Câu không qua kiểm tra bị đánh dấu **Lỗi** và **không bao giờ ghi vào game**.
  Văn bản game được gửi cho AI như dữ liệu, kèm chỉ dẫn không làm theo lệnh nằm trong văn bản.
- **Khóa API:** tệp cấu hình tạo thẳng với quyền 600 trong thư mục 700 (hoặc dùng biến môi trường); không gửi khóa qua
  `http://` tới máy khác; không theo chuyển hướng; hỏi xác nhận trước khi gửi văn bản game ra dịch vụ bên ngoài.
- Công cụ **không** chạy mã của game, không giải nén kho lưu trữ, không `eval`/`exec`.

Giới hạn: đây không phải sandbox; khóa API lưu dạng văn bản thường (quyền 600); chưa chống kẻ tấn công cục bộ đang chủ động đổi
tệp ngay giữa lúc kiểm tra và ghi.

## Giới hạn đã biết
- Không trích: chuỗi của **engine** Ren'Py (hộp thoại xác nhận, công cụ dev...), đoạn `_p("""...""")` (credits), tham số
  plugin RPG Maker (`js/plugins.js`), chữ nằm trong ảnh, game Unity/Godot/Unreal, game Ren'Py chỉ có `.rpyc`.
- RPG Maker: mô tả vật phẩm (khung 2 dòng) và các lựa chọn không tự ngắt dòng; tiếng Việt dài hơn nên có thể bị cắt.
- Cùng một câu gốc chỉ có một bản dịch (ngữ cảnh khác nhau vẫn dùng chung). Ren'Py: ưu tiên bản đã duyệt.

## Checklist test
1. Chạy **Chế độ thử** trên một game nhỏ → Áp dụng → mở game xem có `(VI)` không → Khôi phục → game về như cũ.
2. Chạy AI thật với vài chục câu, xem giọng văn, thêm từ điển/xưng hô rồi dịch lại.
3. RPG Maker: kiểm tra chữ có bị tràn hộp thoại không (chỉnh số ký tự/dòng trong Cài đặt), có hiện ô vuông không (chọn font).
4. Ren'Py: kiểm tra có hiện tiếng Việt không (xem mục trên nếu không).

Test tự động: `python -m pytest tests -q`
