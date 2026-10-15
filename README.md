# ViTrans

ViTrans là công cụ Python hỗ trợ dịch game indie sang tiếng Việt. Công cụ có giao diện đồ họa (PyQt6) và dòng lệnh (CLI), cho phép trích xuất văn bản, dịch, duyệt/sửa bản dịch rồi áp dụng vào game hoặc xuất thành bản vá riêng.

## Tính năng

- **Định dạng hỗ trợ:** RPG Maker MV/MZ, Ren'Py có tệp mã nguồn `.rpy`, và JSON chung ở chế độ quét dự phòng.
- **Dịch:** Claude (Anthropic), API tương thích OpenAI (bao gồm Ollama), Google Dịch và chế độ thử không gọi dịch vụ dịch.
- **Rà soát bản dịch:** chỉnh sửa thủ công, duyệt từng mục, từ điển thuật ngữ, thiết lập giọng văn và cách xưng hô.
- **Giữ mã trong game:** kiểm tra biến/mã định dạng trong câu dịch và cảnh báo một số lỗi trước khi áp dụng.
- **Áp dụng an toàn hơn:** tự sao lưu tệp được sửa vào `.vitrans_backup`, hỗ trợ khôi phục bản gốc hoặc xuất riêng các tệp bản vá.
- **Tùy chỉnh hiển thị:** có tùy chọn ngắt dòng và chọn font khi tạo bản dịch cho các định dạng được hỗ trợ.

## Cài đặt trên Arch Linux

Cài các gói cần thiết:

```bash
sudo pacman -S python python-pyqt6 python-requests python-fonttools unzip
```

Giải nén dự án, vào thư mục và chạy giao diện:

```bash
unzip vitrans_project.zip
cd vitrans_project
python -m vitrans
```

Yêu cầu Python 3.10 trở lên. Trên hệ điều hành khác, có thể cài phụ thuộc bằng môi trường ảo:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m vitrans
```

## Cách sử dụng

1. Mở ViTrans, chọn thư mục game. Công cụ sẽ thử nhận diện loại game; có thể đổi loại ở thanh công cụ nếu cần.
2. Vào **Cài đặt** để chọn nhà cung cấp dịch và cấu hình khóa API, địa chỉ máy chủ hoặc model tương ứng.
3. Trong **Từ điển**, thêm thuật ngữ hoặc gợi ý tên nhân vật. Trong **Phong cách**, chỉnh ngôn ngữ nguồn, thể loại, giọng văn và cách xưng hô.
4. Chọn **Dịch phần chờ**. Kiểm tra các câu dịch, sửa khi cần và duyệt trước khi áp dụng.
5. Chọn **Áp dụng vào game** để ghi tệp đã dịch, hoặc **Xuất bản vá** để tạo thư mục chứa các tệp bản dịch. Dùng **Khôi phục gốc** để khôi phục các tệp đã sao lưu.

Nên chạy **Chế độ thử** trước để kiểm tra quy trình mà không gửi văn bản tới dịch vụ dịch. Khi dùng nhà cung cấp bên ngoài, văn bản game được gửi tới dịch vụ đó; hãy kiểm tra cấu hình và chính sách của nhà cung cấp trước khi sử dụng.

## Dùng dòng lệnh

Chạy các lệnh từ thư mục dự án:

```bash
# Mở giao diện
python -m vitrans

# Quét văn bản trong game
python -m vitrans scan "/duong/dan/toi/game"

# Chạy thử quy trình dịch, không gọi AI
python -m vitrans translate "/duong/dan/toi/game" --provider echo

# Xem thống kê trạng thái bản dịch
python -m vitrans stats "/duong/dan/toi/game"

# Áp dụng bản dịch đã lưu
python -m vitrans apply "/duong/dan/toi/game"

# Xuất bản vá ra thư mục riêng
python -m vitrans export "/duong/dan/toi/game" "./vitrans-patch"

# Khôi phục các tệp đã được sao lưu
python -m vitrans restore "/duong/dan/toi/game"
```

Có thể dùng `--engine rpgmaker`, `--engine renpy` hoặc `--engine generic_json` để chỉ định loại game khi cần. Với lệnh `translate`, `--provider` nhận `anthropic`, `openai`, `google` hoặc `echo`.

## Giới hạn

- Ren'Py cần tệp `.rpy`; game chỉ có `.rpyc` không được giải mã tự động.
- JSON chung là chế độ quét dự phòng, cần kiểm tra kết quả kỹ hơn.
- Công cụ không trích được chữ nằm trong hình ảnh và hiện không có adapter chuyên dụng cho Unity, Godot hoặc Unreal.
- Một số hộp thoại, lựa chọn hoặc mô tả trong game có thể cần chỉnh thủ công nếu bản tiếng Việt dài hơn bản gốc.
- Bản dịch máy có thể sai nghĩa hoặc không phù hợp ngữ cảnh; cần đọc lại trước khi phát hành.

## Chạy kiểm thử

```bash
python -m pip install pytest
python -m pytest tests -q
```
